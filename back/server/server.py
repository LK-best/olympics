# -*- coding: utf-8 -*-
# EduBattle сервер
# написал: ученик 10 класса
# дата: 2026
# переписал на работу с sqlite базой
# теперь данные не теряются при перезапуске
# вебсокеты остались как были

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import json
import os
import hashlib
import time
import asyncio
from datetime import datetime, timedelta

# импортируем хелпер для базы данных
import db_helper as db

# создаём приложуху
app = FastAPI(title="EduBattle")

# cors штука чтоб работало
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

###################################
# мой кастомный генератор id
# теперь не так важен потому что
# sqlite сам генерит id
# но оставил для совместимости
###################################

_moy_schetchik = 0
_poslednie_id = []
_poslednee_vremya = 0


def _poluchit_sluchainoe_chislo(min_val, max_val):
    global _poslednee_vremya

    seed = int(time.time() * 1000000) % 2147483647
    seed = seed + _poslednee_vremya
    _poslednee_vremya = seed % 1000000

    a = 1103515245
    c = 12345
    m = 2147483648

    rezultat = (a * seed + c) % m
    diapason = max_val - min_val + 1
    chislo = min_val + (rezultat % diapason)

    return chislo


def moy_generator_id():
    global _moy_schetchik
    global _poslednie_id

    _moy_schetchik = _moy_schetchik + 1
    if _moy_schetchik > 999999:
        _moy_schetchik = 1

    vremya_ms = int(time.time() * 1000)
    sol_chislo = _poluchit_sluchainoe_chislo(100, 999)
    mikro_sol = int((time.time() % 1) * 1000000) % 1000

    kombinaciya = vremya_ms * 1000 + _moy_schetchik * 7 + sol_chislo + mikro_sol

    vremya_str = str(time.time())
    hesh_chast = 0
    idx = 0
    while idx < len(vremya_str):
        simvol = vremya_str[idx]
        if simvol.isdigit():
            hesh_chast = hesh_chast + int(simvol) * (idx + 1)
        idx = idx + 1

    kombinaciya = kombinaciya + hesh_chast

    popytka = 0
    while kombinaciya in _poslednie_id:
        dop_sol = _poluchit_sluchainoe_chislo(1, 1000)
        kombinaciya = kombinaciya + dop_sol
        popytka = popytka + 1
        if popytka > 10:
            kombinaciya = kombinaciya + int(time.time())
            break

    _poslednie_id.append(kombinaciya)
    if len(_poslednie_id) > 100:
        _poslednie_id.pop(0)

    return kombinaciya


###################################
# сортировки (оставил для совместимости)
###################################

def moya_sortirovka_po_polyu(spisok, pole, po_vozrastaniyu=True):
    rezultat = []
    i = 0
    while i < len(spisok):
        rezultat.append(spisok[i])
        i = i + 1

    n = len(rezultat)
    i = 0
    while i < n:
        j = 0
        while j < n - i - 1:
            znach1 = rezultat[j].get(pole, 0)
            znach2 = rezultat[j + 1].get(pole, 0)

            nado_menyat = False
            if po_vozrastaniyu == True:
                if znach1 > znach2:
                    nado_menyat = True
            else:
                if znach1 < znach2:
                    nado_menyat = True

            if nado_menyat == True:
                temp = rezultat[j]
                rezultat[j] = rezultat[j + 1]
                rezultat[j + 1] = temp

            j = j + 1
        i = i + 1

    return rezultat


def moy_shuffle(spisok):
    rezultat = []
    i = 0
    while i < len(spisok):
        rezultat.append(spisok[i])
        i = i + 1

    n = len(rezultat)
    i = n - 1
    while i > 0:
        j = _poluchit_sluchainoe_chislo(0, i)
        temp = rezultat[i]
        rezultat[i] = rezultat[j]
        rezultat[j] = temp
        i = i - 1

    return rezultat


###################################
# WebSocket менеджер
###################################

class MoyWebSocketManager:
    def __init__(self):
        self.aktivnie_sockety: Dict[int, List[WebSocket]] = {}
        self.user_sockety: Dict[int, WebSocket] = {}
        self.user_match: Dict[int, int] = {}
        self.ochered_soobsheniy: Dict[int, List[dict]] = {}
        self.poslednie_pingi: Dict[int, float] = {}

    async def podkluchit(self, websocket: WebSocket, match_id: int, user_id: int):
        await websocket.accept()

        if match_id not in self.aktivnie_sockety:
            self.aktivnie_sockety[match_id] = []

        self.aktivnie_sockety[match_id].append(websocket)
        self.user_sockety[user_id] = websocket
        self.user_match[user_id] = match_id
        self.poslednie_pingi[user_id] = time.time()

        if user_id in self.ochered_soobsheniy:
            soobsheniya = self.ochered_soobsheniy[user_id]
            i = 0
            while i < len(soobsheniya):
                try:
                    await websocket.send_json(soobsheniya[i])
                except:
                    pass
                i = i + 1
            self.ochered_soobsheniy[user_id] = []

        print("подключился user " + str(user_id) + " к матчу " + str(match_id))

        await self.otpravit_v_match(match_id, {
            "type": "user_connected",
            "user_id": user_id,
            "time": time.time()
        })

    def otkluchit(self, websocket: WebSocket, match_id: int, user_id: int):
        if match_id in self.aktivnie_sockety:
            noviy_spisok = []
            i = 0
            while i < len(self.aktivnie_sockety[match_id]):
                if self.aktivnie_sockety[match_id][i] != websocket:
                    noviy_spisok.append(self.aktivnie_sockety[match_id][i])
                i = i + 1
            self.aktivnie_sockety[match_id] = noviy_spisok

            if len(self.aktivnie_sockety[match_id]) == 0:
                del self.aktivnie_sockety[match_id]

        if user_id in self.user_sockety:
            del self.user_sockety[user_id]
        if user_id in self.user_match:
            del self.user_match[user_id]
        if user_id in self.poslednie_pingi:
            del self.poslednie_pingi[user_id]

        print("отключился user " + str(user_id))

    async def otpravit_v_match(self, match_id: int, soobshenie: dict):
        if match_id in self.aktivnie_sockety:
            sockety = self.aktivnie_sockety[match_id]
            i = 0
            while i < len(sockety):
                try:
                    await sockety[i].send_json(soobshenie)
                except Exception as e:
                    print("ошибка отправки: " + str(e))
                i = i + 1

    async def otpravit_useru(self, user_id: int, soobshenie: dict):
        if user_id in self.user_sockety:
            try:
                await self.user_sockety[user_id].send_json(soobshenie)
            except:
                if user_id not in self.ochered_soobsheniy:
                    self.ochered_soobsheniy[user_id] = []
                self.ochered_soobsheniy[user_id].append(soobshenie)
        else:
            if user_id not in self.ochered_soobsheniy:
                self.ochered_soobsheniy[user_id] = []
            self.ochered_soobsheniy[user_id].append(soobshenie)

    def obnovit_ping(self, user_id: int):
        self.poslednie_pingi[user_id] = time.time()


ws_manager = MoyWebSocketManager()


###################################
# вспомогательные функции
###################################

def zashifrovat_parol(parol):
    sol = "moy_secret_sol_2024"
    vmeste = parol + sol
    hesh = hashlib.sha256(vmeste.encode()).hexdigest()
    return hesh


def proverit_dostizheniya(user_id):
    # получаем данные юзера
    user = db.poluchit_usera_po_id(user_id)
    if user == None:
        return []

    novie = []
    tekushie_achi = user.get("achievements", [])
    stats = user.get("stats", {})

    # первая задача
    if "first_task" not in tekushie_achi:
        if stats.get("solved", 0) >= 1:
            db.dobavit_dostizhenie(user_id, "first_task")
            db.obnovit_usera(user_id, xp=user.get("xp", 0) + 10)
            novie.append({"id": "first_task", "name": "Первый шаг", "xp": 10})

    # 10 задач
    if "ten_tasks" not in tekushie_achi:
        if stats.get("solved", 0) >= 10:
            db.dobavit_dostizhenie(user_id, "ten_tasks")
            db.obnovit_usera(user_id, xp=user.get("xp", 0) + 50)
            novie.append({"id": "ten_tasks", "name": "Начинающий", "xp": 50})

    # 50 задач
    if "fifty_tasks" not in tekushie_achi:
        if stats.get("solved", 0) >= 50:
            db.dobavit_dostizhenie(user_id, "fifty_tasks")
            db.obnovit_usera(user_id, xp=user.get("xp", 0) + 200)
            novie.append({"id": "fifty_tasks", "name": "Упорный", "xp": 200})

    # первая победа
    if "first_win" not in tekushie_achi:
        if stats.get("wins", 0) >= 1:
            db.dobavit_dostizhenie(user_id, "first_win")
            db.obnovit_usera(user_id, xp=user.get("xp", 0) + 100)
            novie.append({"id": "first_win", "name": "Победитель", "xp": 100})

    # 10 побед
    if "ten_wins" not in tekushie_achi:
        if stats.get("wins", 0) >= 10:
            db.dobavit_dostizhenie(user_id, "ten_wins")
            db.obnovit_usera(user_id, xp=user.get("xp", 0) + 300)
            novie.append({"id": "ten_wins", "name": "Боец", "xp": 300})

    return novie


def poschitat_elo(moy_reyting, ego_reyting, rezultat):
    K = 32
    raznica = ego_reyting - moy_reyting
    stepen = raznica / 400.0

    desyat_v_stepeni = 1.0
    if stepen >= 0:
        i = 0
        while i < int(stepen):
            desyat_v_stepeni = desyat_v_stepeni * 10
            i = i + 1
        drobnaya = stepen - int(stepen)
        if drobnaya > 0:
            desyat_v_stepeni = desyat_v_stepeni * (1 + drobnaya * 2.302585)
    else:
        stepen_abs = -stepen
        i = 0
        while i < int(stepen_abs):
            desyat_v_stepeni = desyat_v_stepeni * 10
            i = i + 1
        drobnaya = stepen_abs - int(stepen_abs)
        if drobnaya > 0:
            desyat_v_stepeni = desyat_v_stepeni * (1 + drobnaya * 2.302585)
        desyat_v_stepeni = 1.0 / desyat_v_stepeni

    ozhidaemiy = 1.0 / (1.0 + desyat_v_stepeni)

    if rezultat == "win":
        fakt = 1.0
    elif rezultat == "loss":
        fakt = 0.0
    else:
        fakt = 0.5

    izmenenie = K * (fakt - ozhidaemiy)

    if izmenenie >= 0:
        izmenenie = int(izmenenie + 0.5)
    else:
        izmenenie = int(izmenenie - 0.5)

    return izmenenie


def format_user_for_response(user):
    # форматируем юзера для ответа (убираем пароль и т.д.)
    if user == None:
        return None

    otvet = {
        "id": user.get("id"),
        "name": user.get("name") or user.get("username"),
        "email": user.get("email"),
        "isAdmin": user.get("isAdmin", False) or user.get("is_admin", 0) == 1,
        "level": user.get("level", 1),
        "xp": user.get("xp", 0),
        "rating": user.get("rating", 1000),
        "stats": user.get("stats", {"solved": 0, "correct": 0, "wins": 0, "losses": 0, "draws": 0}),
        "achievements": user.get("achievements", []),
        "subjectStats": user.get("subjectStats", {}),
    }

    # история
    history = db.poluchit_istoriyu(user["id"], 50)
    otvet["history"] = []
    if history != None:
        for h in history:
            otvet["history"].append({
                "text": h.get("action_text", ""),
                "date": h.get("action_date", ""),
                "timestamp": h.get("created_at", 0)
            })

    # история матчей
    match_history = db.poluchit_istoriyu_matchey_usera(user["id"], 20)
    otvet["matchHistory"] = []
    if match_history != None:
        for mh in match_history:
            otvet["matchHistory"].append({
                "match_id": mh.get("match_id"),
                "opponent": mh.get("opponent_name"),
                "opponentRating": mh.get("opponent_rating"),
                "myScore": mh.get("my_score"),
                "oppScore": mh.get("opp_score"),
                "result": mh.get("result"),
                "ratingChange": mh.get("rating_change"),
                "date": mh.get("match_date"),
                "subject": mh.get("subject"),
                "mode": mh.get("mode")
            })

    return otvet


###################################
# модели данных (pydantic)
###################################

class RegData(BaseModel):
    name: str
    email: str
    password: str


class LoginData(BaseModel):
    email: str
    password: str


class NewTask(BaseModel):
    subject: str
    difficulty: str
    topic: str
    question: str
    options: List[str]
    answer: str
    hint: str = ""


class TrenigResult(BaseModel):
    user_id: int
    tasks_solved: int
    correct_count: int
    xp_earned: int
    subject: str


class MatchSearchData(BaseModel):
    user_id: int
    subject: str
    mode: str


class MatchAnswerData(BaseModel):
    match_id: int
    user_id: int
    task_index: int
    answer: str
    time_spent: float = 0


class MatchEndData(BaseModel):
    match_id: int
    user_id: int
    result: str


###################################
# WebSocket эндпоинт
###################################

@app.websocket("/ws/match/{match_id}/{user_id}")
async def websocket_match(websocket: WebSocket, match_id: int, user_id: int):
    await ws_manager.podkluchit(websocket, match_id, user_id)

    try:
        while True:
            data = await websocket.receive_json()
            tip = data.get("type", "")

            if tip == "ping":
                ws_manager.obnovit_ping(user_id)
                await websocket.send_json({"type": "pong", "time": time.time()})

            elif tip == "answer":
                result = await obrabota_otvet_ws(data, match_id, user_id)
                await ws_manager.otpravit_v_match(match_id, result)

            elif tip == "get_state":
                state = poluchit_sostoyanie_dlya_ws(match_id, user_id)
                await websocket.send_json({"type": "state", "data": state})

            elif tip == "chat":
                soobshenie = {
                    "type": "chat",
                    "user_id": user_id,
                    "text": data.get("text", ""),
                    "time": time.time()
                }
                await ws_manager.otpravit_v_match(match_id, soobshenie)

            elif tip == "ready":
                await ws_manager.otpravit_v_match(match_id, {
                    "type": "player_ready",
                    "user_id": user_id,
                    "time": time.time()
                })

    except WebSocketDisconnect:
        ws_manager.otkluchit(websocket, match_id, user_id)
        await ws_manager.otpravit_v_match(match_id, {
            "type": "opponent_disconnected",
            "user_id": user_id,
            "time": time.time()
        })
    except Exception as e:
        print("websocket ошибка: " + str(e))
        ws_manager.otkluchit(websocket, match_id, user_id)


async def obrabota_otvet_ws(data, match_id, user_id):
    m = db.poluchit_match_po_id(match_id)

    if m == None:
        return {"type": "error", "message": "матч не найден"}

    task_index = data.get("task_index", 0)
    answer = data.get("answer", "")
    time_spent = data.get("time_spent", 0)

    if task_index < 0 or task_index >= len(m["tasks"]):
        return {"type": "error", "message": "неверный индекс задачи"}

    zadacha = m["tasks"][task_index]
    pravilno = answer == zadacha["answer"]

    # определяем игрока
    if m["player1_id"] == user_id:
        otvety = m["player1_answers"]
        schet = m["player1_score"]
        schet_key = "player1_score"
        otvety_key = "player1_answers"
    elif m["player2_id"] == user_id:
        otvety = m["player2_answers"]
        schet = m["player2_score"]
        schet_key = "player2_score"
        otvety_key = "player2_answers"
    else:
        return {"type": "error", "message": "вы не участник"}

    # проверяем был ли уже ответ
    uzhe_otvetil = False
    j = 0
    while j < len(otvety):
        if otvety[j]["task_index"] == task_index:
            uzhe_otvetil = True
            if otvety[j]["correct"] == True:
                schet = schet - 1
            otvety[j]["answer"] = answer
            otvety[j]["correct"] = pravilno
            otvety[j]["time_spent"] = time_spent
            otvety[j]["updated_at"] = time.time()
            break
        j = j + 1

    if uzhe_otvetil == False:
        noviy_otvet = {
            "task_index": task_index,
            "answer": answer,
            "correct": pravilno,
            "time_spent": time_spent,
            "created_at": time.time(),
            "updated_at": time.time()
        }
        otvety.append(noviy_otvet)

    if pravilno == True:
        schet = schet + 1

    # обновляем матч
    update_data = {otvety_key: otvety, schet_key: schet}

    # если бот - симулируем ответ
    if m.get("is_bot", False) == True and m["player2_id"] == 0:
        bot_otvetil = False
        k = 0
        while k < len(m["player2_answers"]):
            if m["player2_answers"][k]["task_index"] == task_index:
                bot_otvetil = True
                break
            k = k + 1

        if bot_otvetil == False:
            bazoviy_shans = 0.5
            bonus = (m["player2_rating"] - 1000) / 2000
            shans = bazoviy_shans + bonus
            if shans < 0.3:
                shans = 0.3
            if shans > 0.8:
                shans = 0.8

            sluch = _poluchit_sluchainoe_chislo(1, 100) / 100.0
            bot_pravilno = sluch < shans
            bot_time = _poluchit_sluchainoe_chislo(30, 150) / 10.0

            if bot_pravilno:
                bot_answer = zadacha["answer"]
            else:
                nepravilnie = []
                for opt in zadacha["options"]:
                    if opt != zadacha["answer"]:
                        nepravilnie.append(opt)
                if len(nepravilnie) > 0:
                    idx = _poluchit_sluchainoe_chislo(0, len(nepravilnie) - 1)
                    bot_answer = nepravilnie[idx]
                else:
                    bot_answer = zadacha["options"][0]

            bot_otvet = {
                "task_index": task_index,
                "answer": bot_answer,
                "correct": bot_pravilno,
                "time_spent": bot_time,
                "created_at": time.time(),
                "updated_at": time.time()
            }
            m["player2_answers"].append(bot_otvet)
            update_data["player2_answers"] = m["player2_answers"]

            if bot_pravilno == True:
                update_data["player2_score"] = m["player2_score"] + 1

    db.obnovit_match(match_id, **update_data)

    # получаем обновленный матч
    m = db.poluchit_match_po_id(match_id)

    result = {
        "type": "answer_result",
        "user_id": user_id,
        "task_index": task_index,
        "correct": pravilno,
        "correct_answer": zadacha["answer"],
        "player1_score": m["player1_score"],
        "player2_score": m["player2_score"],
        "time_spent": time_spent,
        "timestamp": time.time()
    }

    return result


def poluchit_sostoyanie_dlya_ws(match_id, user_id):
    m = db.poluchit_match_po_id(match_id)

    if m == None:
        return None

    if m["player1_id"] == user_id:
        moy_schet = m["player1_score"]
        ego_schet = m["player2_score"]
        moi_otvety = m["player1_answers"]
        ego_otvety = m["player2_answers"]
        ego_imya = m["player2_name"]
        ya_player1 = True
    else:
        moy_schet = m["player2_score"]
        ego_schet = m["player1_score"]
        moi_otvety = m["player2_answers"]
        ego_otvety = m["player1_answers"]
        ego_imya = m["player1_name"]
        ya_player1 = False

    return {
        "match_id": m["id"],
        "status": m["status"],
        "my_score": moy_schet,
        "opp_score": ego_schet,
        "opp_name": ego_imya,
        "tasks": m["tasks"],
        "my_answers": moi_otvety,
        "opp_answers": ego_otvety,
        "am_player1": ya_player1,
        "is_bot": m.get("is_bot", False),
        "timestamp": time.time()
    }


###################################
# API - регистрация и вход
###################################

@app.post("/api/register")
def registraciya(data: RegData):
    # проверяем емейл
    existing = db.poluchit_usera_po_email(data.email)
    if existing != None:
        raise HTTPException(status_code=400, detail="Такой email уже есть")

    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Пароль минимум 6 символов")

    hesh = zashifrovat_parol(data.password)
    user_id = db.sozdat_usera(data.name, data.email, hesh)

    user = db.poluchit_usera_po_id(user_id)
    otvet = format_user_for_response(user)

    return {"success": True, "user": otvet}


@app.post("/api/login")
def vhod(data: LoginData):
    user = db.poluchit_usera_po_email(data.email)

    if user == None:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    hesh = zashifrovat_parol(data.password)

    if user.get("password_hash") != hesh:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    otvet = format_user_for_response(user)
    return {"success": True, "user": otvet}


@app.get("/api/user/{user_id}")
def poluchit_usera(user_id: int):
    user = db.poluchit_usera_po_id(user_id)

    if user == None:
        raise HTTPException(status_code=404, detail="Юзер не найден")

    return format_user_for_response(user)


###################################
# API - статистика по дням
###################################

@app.get("/api/user/{user_id}/daily_stats")
def poluchit_statistiku_po_dnyam(user_id: int):
    stats = db.poluchit_stats_po_dnyam_nedeli(user_id)

    dni_v_poryadke = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    grafik_data = []

    i = 0
    while i < len(dni_v_poryadke):
        den = dni_v_poryadke[i]
        if den in stats:
            grafik_data.append({
                "day": den,
                "solved": stats[den]["solved"],
                "correct": stats[den]["correct"]
            })
        else:
            grafik_data.append({"day": den, "solved": 0, "correct": 0})
        i = i + 1

    return {"stats": grafik_data}


@app.get("/api/user/{user_id}/weekly_stats")
def poluchit_statistiku_za_nedelyu(user_id: int):
    result = db.poluchit_stats_za_nedelyu(user_id)
    return {"stats": result}


###################################
# API - детальная статистика матча
###################################

@app.get("/api/match/{match_id}/details")
def poluchit_detali_matcha(match_id: int, user_id: int):
    m = db.poluchit_match_po_id(match_id)

    if m == None:
        raise HTTPException(status_code=404, detail="Матч не найден")

    if m["player1_id"] != user_id and m["player2_id"] != user_id:
        raise HTTPException(status_code=403, detail="Вы не участник матча")

    if m["player1_id"] == user_id:
        moi_otvety = m.get("player1_answers", [])
        ego_otvety = m.get("player2_answers", [])
        moy_schet = m["player1_score"]
        ego_schet = m["player2_score"]
        ego_imya = m["player2_name"]
        ego_reyting = m["player2_rating"]
    else:
        moi_otvety = m.get("player2_answers", [])
        ego_otvety = m.get("player1_answers", [])
        moy_schet = m["player2_score"]
        ego_schet = m["player1_score"]
        ego_imya = m["player1_name"]
        ego_reyting = m["player1_rating"]

    zadachi_detali = []
    j = 0
    while j < len(m["tasks"]):
        task = m["tasks"][j]

        moy_otvet = None
        moe_vremya = 0
        ya_pravilno = False
        ya_otvetil = False

        k = 0
        while k < len(moi_otvety):
            if moi_otvety[k]["task_index"] == j:
                moy_otvet = moi_otvety[k].get("answer")
                moe_vremya = moi_otvety[k].get("time_spent", 0)
                ya_pravilno = moi_otvety[k].get("correct", False)
                ya_otvetil = True
                break
            k = k + 1

        ego_otvet = None
        ego_vremya = 0
        on_pravilno = False
        on_otvetil = False

        k = 0
        while k < len(ego_otvety):
            if ego_otvety[k]["task_index"] == j:
                ego_otvet = ego_otvety[k].get("answer")
                ego_vremya = ego_otvety[k].get("time_spent", 0)
                on_pravilno = ego_otvety[k].get("correct", False)
                on_otvetil = True
                break
            k = k + 1

        detal = {
            "index": j,
            "question": task["question"],
            "options": task["options"],
            "correct_answer": task["answer"],
            "hint": task.get("hint", ""),
            "topic": task.get("topic", ""),
            "difficulty": task.get("difficulty", ""),
            "my_answer": moy_otvet,
            "my_time": round(moe_vremya, 2),
            "my_correct": ya_pravilno,
            "my_answered": ya_otvetil,
            "opp_answer": ego_otvet,
            "opp_time": round(ego_vremya, 2),
            "opp_correct": on_pravilno,
            "opp_answered": on_otvetil
        }

        zadachi_detali.append(detal)
        j = j + 1

    # среднее время
    summa_moego = 0
    kol_moih = 0
    for o in moi_otvety:
        summa_moego = summa_moego + o.get("time_spent", 0)
        kol_moih = kol_moih + 1
    srednee_moe = summa_moego / kol_moih if kol_moih > 0 else 0

    summa_ego = 0
    kol_ego = 0
    for o in ego_otvety:
        summa_ego = summa_ego + o.get("time_spent", 0)
        kol_ego = kol_ego + 1
    srednee_ego = summa_ego / kol_ego if kol_ego > 0 else 0

    if moy_schet > ego_schet:
        rezultat = "win"
    elif moy_schet < ego_schet:
        rezultat = "loss"
    else:
        rezultat = "draw"

    obshaya_stat = {
        "match_id": m["id"],
        "status": m["status"],
        "my_score": moy_schet,
        "opp_score": ego_schet,
        "opp_name": ego_imya,
        "opp_rating": ego_reyting,
        "subject": m["subject"],
        "mode": m["mode"],
        "is_bot": m.get("is_bot", False),
        "tasks_count": len(m["tasks"]),
        "my_avg_time": round(srednee_moe, 2),
        "opp_avg_time": round(srednee_ego, 2),
        "result": rezultat,
        "my_answered_count": kol_moih,
        "opp_answered_count": kol_ego
    }

    return {"summary": obshaya_stat, "tasks": zadachi_detali}


@app.get("/api/user/{user_id}/match_history_detailed")
def poluchit_istoriyu_matchey_detalno(user_id: int, limit: int = 10):
    matchi = db.poluchit_vse_matchi()
    moi_matchi = []

    for m in matchi:
        if m["player1_id"] == user_id or m["player2_id"] == user_id:
            if m["player1_id"] == user_id:
                moy_schet = m["player1_score"]
                ego_schet = m["player2_score"]
                ego_imya = m["player2_name"]
                ego_reyting = m["player2_rating"]
            else:
                moy_schet = m["player2_score"]
                ego_schet = m["player1_score"]
                ego_imya = m["player1_name"]
                ego_reyting = m["player1_rating"]

            if moy_schet > ego_schet:
                rezultat = "win"
            elif moy_schet < ego_schet:
                rezultat = "loss"
            else:
                rezultat = "draw"

            zapis = {
                "match_id": m["id"],
                "opponent": ego_imya,
                "opponent_rating": ego_reyting,
                "my_score": moy_schet,
                "opp_score": ego_schet,
                "result": rezultat,
                "subject": m["subject"],
                "mode": m["mode"],
                "status": m["status"],
                "is_bot": m.get("is_bot", False),
                "tasks_count": len(m.get("tasks", []))
            }
            moi_matchi.append(zapis)

    # берём только limit записей
    rezultat = moi_matchi[:limit]

    return {"matches": rezultat, "total": len(moi_matchi)}


###################################
# API - задачи
###################################

@app.get("/api/tasks")
def poluchit_zadachi(subject: str = "", difficulty: str = "", topic: str = "", search: str = ""):
    tasks = db.poluchit_zadachi_s_filtrami(
        subject=subject if subject else None,
        difficulty=difficulty if difficulty else None,
        topic=topic if topic else None,
        search=search if search else None
    )
    return tasks if tasks else []


@app.post("/api/tasks")
def dobavit_zadachu(task: NewTask):
    task_id = db.sozdat_zadachu(
        task.subject, task.difficulty, task.topic,
        task.question, task.options, task.answer, task.hint
    )

    novaya = db.poluchit_zadachu_po_id(task_id)
    return {"success": True, "task": novaya}


@app.delete("/api/tasks/{task_id}")
def udalit_zadachu(task_id: int):
    task = db.poluchit_zadachu_po_id(task_id)
    if task == None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    db.udalit_zadachu(task_id)
    return {"success": True}


###################################
# API - тренировка
###################################

@app.post("/api/training/start")
def nachat_trenirovku(subject: str, difficulty: str, count: int, user_id: int):
    user = db.poluchit_usera_po_id(user_id)
    user_lvl = user.get("level", 1) if user else 1

    # получаем все задачи по предмету
    all_tasks = db.poluchit_zadachi_s_filtrami(subject=subject)

    podhodyashie = []
    for task in all_tasks:
        if difficulty == "adaptive":
            if user_lvl <= 3:
                if task["difficulty"] == "easy":
                    podhodyashie.append(task)
            elif user_lvl <= 6:
                if task["difficulty"] != "hard":
                    podhodyashie.append(task)
            else:
                podhodyashie.append(task)
        else:
            if task["difficulty"] == difficulty:
                podhodyashie.append(task)

    peremeshannye = moy_shuffle(podhodyashie)

    vibrannie = []
    i = 0
    while i < count and i < len(peremeshannye):
        vibrannie.append(peremeshannye[i])
        i = i + 1

    if len(vibrannie) == 0:
        raise HTTPException(status_code=404, detail="Нет задач по таким критериям")

    return {"tasks": vibrannie, "count": len(vibrannie)}


@app.post("/api/training/result")
def sohranit_rezultat_trenirovki(data: TrenigResult):
    user = db.poluchit_usera_po_id(data.user_id)

    if user == None:
        raise HTTPException(status_code=404, detail="Юзер не найден")

    # обновляем статистику
    new_solved = user.get("solved_count", 0) + data.tasks_solved
    new_correct = user.get("correct_count", 0) + data.correct_count
    new_xp = user.get("xp", 0) + data.xp_earned
    new_level = user.get("level", 1)

    # проверяем уровень
    xp_dlya_lvla = new_level * 100
    while new_xp >= xp_dlya_lvla:
        new_level = new_level + 1
        xp_dlya_lvla = new_level * 100

    # статистика по предмету
    subject_stats = user.get("subjectStats", {})
    if data.subject not in subject_stats:
        subject_stats[data.subject] = {"solved": 0, "correct": 0}
    subject_stats[data.subject]["solved"] = subject_stats[data.subject]["solved"] + data.tasks_solved
    subject_stats[data.subject]["correct"] = subject_stats[data.subject]["correct"] + data.correct_count

    # обновляем юзера
    db.obnovit_usera(data.user_id,
                     solved_count=new_solved,
                     correct_count=new_correct,
                     xp=new_xp,
                     level=new_level,
                     subject_stats=json.dumps(subject_stats)
                     )

    # добавляем в историю
    zapis = "Тренировка: " + str(data.correct_count) + "/" + str(data.tasks_solved)
    db.dobavit_v_istoriyu(data.user_id, zapis)

    # обновляем статистику по дням
    db.obnovit_daily_stats(data.user_id, data.tasks_solved, data.correct_count, data.subject)

    # проверяем достижения
    novie_achi = proverit_dostizheniya(data.user_id)

    # получаем обновленного юзера
    user = db.poluchit_usera_po_id(data.user_id)
    otvet = format_user_for_response(user)

    return {"success": True, "user": otvet, "new_achievements": novie_achi}


###################################
# API - PvP матчи
###################################

@app.post("/api/match/search")
def iskat_match(data: MatchSearchData):
    user = db.poluchit_usera_po_id(data.user_id)
    if user == None:
        raise HTTPException(status_code=404, detail="Юзер не найден")

    # проверяем не в очереди ли уже
    poziciya = db.poluchit_poziciyu_v_ocheredi(data.user_id)
    if poziciya >= 0:
        ochered = db.poluchit_ochered()
        return {"status": "waiting", "queue_id": ochered[poziciya]["id"], "position": poziciya + 1}

    # проверяем нет ли активного матча
    aktivnie = db.poluchit_aktivnie_matchi_usera(data.user_id)
    if len(aktivnie) > 0:
        return {"status": "in_match", "match_id": aktivnie[0]["id"]}

    # ищем соперника
    sopernik_v_ocheredi = db.nayti_sopernika_v_ocheredi(
        data.user_id, user.get("rating", 1000), data.subject, data.mode
    )

    if sopernik_v_ocheredi != None:
        # нашли соперника!
        sopernik = db.poluchit_usera_po_id(sopernik_v_ocheredi["user_id"])

        # убираем из очереди
        db.ubrat_iz_ocheredi(sopernik_v_ocheredi["user_id"])

        # выбираем задачи
        all_tasks = db.poluchit_zadachi_s_filtrami(subject=data.subject)
        match_taski = moy_shuffle(all_tasks)

        vibrannie_taski = []
        i = 0
        while i < 5 and i < len(match_taski):
            vibrannie_taski.append(match_taski[i])
            i = i + 1

        # если мало задач, добавляем другие
        if len(vibrannie_taski) < 5:
            drugie = db.poluchit_vse_zadachi()
            drugie = [t for t in drugie if t["subject"] != data.subject]
            drugie = moy_shuffle(drugie)
            while len(vibrannie_taski) < 5 and len(drugie) > 0:
                vibrannie_taski.append(drugie[0])
                drugie.pop(0)

        # создаём матч
        match_id = db.sozdat_match(
            sopernik["id"], sopernik.get("name") or sopernik.get("username"),
            sopernik.get("rating", 1000),
            user["id"], user.get("name") or user.get("username"),
            user.get("rating", 1000),
            data.subject, data.mode, vibrannie_taski, False
        )

        noviy_match = db.poluchit_match_po_id(match_id)
        return {"status": "matched", "match": noviy_match}

    else:
        # не нашли - добавляем в очередь
        queue_id = db.dobavit_v_ochered(
            data.user_id,
            user.get("name") or user.get("username"),
            user.get("rating", 1000),
            data.subject,
            data.mode
        )

        poziciya = db.poluchit_poziciyu_v_ocheredi(data.user_id)
        return {"status": "waiting", "queue_id": queue_id, "position": poziciya + 1}


@app.get("/api/match/check_queue/{user_id}")
def proverit_ochered(user_id: int):
    # проверяем активный матч
    aktivnie = db.poluchit_aktivnie_matchi_usera(user_id)
    if len(aktivnie) > 0:
        return {"status": "matched", "match": aktivnie[0]}

    # проверяем очередь
    poziciya = db.poluchit_poziciyu_v_ocheredi(user_id)
    if poziciya >= 0:
        ochered = db.poluchit_ochered()
        return {"status": "waiting", "position": poziciya + 1, "queue_id": ochered[poziciya]["id"]}

    return {"status": "not_in_queue"}


@app.post("/api/match/cancel_search/{user_id}")
def otmenit_poisk(user_id: int):
    poziciya = db.poluchit_poziciyu_v_ocheredi(user_id)
    ubral = poziciya >= 0
    db.ubrat_iz_ocheredi(user_id)
    return {"success": True, "was_in_queue": ubral}


@app.post("/api/match/play_with_bot")
def igrat_s_botom(data: MatchSearchData):
    user = db.poluchit_usera_po_id(data.user_id)
    if user == None:
        raise HTTPException(status_code=404, detail="Юзер не найден")

    # убираем из очереди если был
    db.ubrat_iz_ocheredi(data.user_id)

    # выбираем задачи
    all_tasks = db.poluchit_zadachi_s_filtrami(subject=data.subject)
    match_taski = moy_shuffle(all_tasks)

    vibrannie_taski = []
    i = 0
    while i < 5 and i < len(match_taski):
        vibrannie_taski.append(match_taski[i])
        i = i + 1

    if len(vibrannie_taski) < 5:
        drugie = db.poluchit_vse_zadachi()
        drugie = [t for t in drugie if t["subject"] != data.subject]
        drugie = moy_shuffle(drugie)
        while len(vibrannie_taski) < 5 and len(drugie) > 0:
            vibrannie_taski.append(drugie[0])
            drugie.pop(0)

    # имена ботов
    bot_imena = ["Умник_2024", "MathPro", "Знайка", "Эрудит", "BrainMaster", "Гений99", "SmartBot", "Quiz_Master"]
    bot_idx = _poluchit_sluchainoe_chislo(0, len(bot_imena) - 1)
    bot_imya = bot_imena[bot_idx]
    bot_reyting = user.get("rating", 1000) + _poluchit_sluchainoe_chislo(-100, 100)

    # создаём матч с ботом
    match_id = db.sozdat_match(
        data.user_id, user.get("name") or user.get("username"), user.get("rating", 1000),
        0, bot_imya, bot_reyting,
        data.subject, data.mode, vibrannie_taski, True
    )

    noviy_match = db.poluchit_match_po_id(match_id)
    return {"success": True, "match": noviy_match}


@app.get("/api/match/state/{match_id}")
def poluchit_sostoyanie_matcha(match_id: int, user_id: int):
    m = db.poluchit_match_po_id(match_id)

    if m == None:
        raise HTTPException(status_code=404, detail="Матч не найден")

    if m["player1_id"] != user_id and m["player2_id"] != user_id:
        raise HTTPException(status_code=403, detail="Вы не участник матча")

    if m["player1_id"] == user_id:
        moy_schet = m["player1_score"]
        ego_schet = m["player2_score"]
        moi_otvety = m["player1_answers"]
        ego_otvety = m["player2_answers"]
        ego_imya = m["player2_name"]
        ego_reyting = m["player2_rating"]
        ya_player1 = True
    else:
        moy_schet = m["player2_score"]
        ego_schet = m["player1_score"]
        moi_otvety = m["player2_answers"]
        ego_otvety = m["player1_answers"]
        ego_imya = m["player1_name"]
        ego_reyting = m["player1_rating"]
        ya_player1 = False

    return {
        "match_id": m["id"],
        "status": m["status"],
        "my_score": moy_schet,
        "opp_score": ego_schet,
        "opp_name": ego_imya,
        "opp_rating": ego_reyting,
        "current_task": m["current_task"],
        "tasks": m["tasks"],
        "my_answers": moi_otvety,
        "opp_answers": ego_otvety,
        "am_player1": ya_player1,
        "mode": m["mode"],
        "is_bot": m.get("is_bot", False)
    }


@app.post("/api/match/answer")
def otpravit_otvet(data: MatchAnswerData):
    m = db.poluchit_match_po_id(data.match_id)

    if m == None:
        raise HTTPException(status_code=404, detail="Матч не найден")

    if m["status"] != "active":
        raise HTTPException(status_code=400, detail="Матч уже завершён")

    kolichestvo_zadach = len(m["tasks"])
    if data.task_index < 0 or data.task_index >= kolichestvo_zadach:
        raise HTTPException(status_code=400, detail="Неверный номер задачи")

    zadacha = m["tasks"][data.task_index]
    pravilno = data.answer == zadacha["answer"]

    if m["player1_id"] == data.user_id:
        otvety = m["player1_answers"]
        schet = m["player1_score"]
        otvety_key = "player1_answers"
        schet_key = "player1_score"
    elif m["player2_id"] == data.user_id:
        otvety = m["player2_answers"]
        schet = m["player2_score"]
        otvety_key = "player2_answers"
        schet_key = "player2_score"
    else:
        raise HTTPException(status_code=403, detail="Вы не участник матча")

    # проверяем был ли уже ответ
    predidushiy = None
    j = 0
    while j < len(otvety):
        if otvety[j]["task_index"] == data.task_index:
            predidushiy = otvety[j]
            break
        j = j + 1

    if predidushiy != None:
        if predidushiy["correct"] == True:
            schet = schet - 1
        predidushiy["answer"] = data.answer
        predidushiy["correct"] = pravilno
        predidushiy["time_spent"] = data.time_spent
        predidushiy["updated_at"] = time.time()
    else:
        noviy_otvet = {
            "task_index": data.task_index,
            "answer": data.answer,
            "correct": pravilno,
            "time_spent": data.time_spent,
            "created_at": time.time(),
            "updated_at": time.time()
        }
        otvety.append(noviy_otvet)

    if pravilno == True:
        schet = schet + 1

    update_data = {otvety_key: otvety, schet_key: schet}

    # если бот - симулируем ответ
    if m.get("is_bot", False) == True and m["player2_id"] == 0:
        bot_otvetil = False
        k = 0
        while k < len(m["player2_answers"]):
            if m["player2_answers"][k]["task_index"] == data.task_index:
                bot_otvetil = True
                break
            k = k + 1

        if bot_otvetil == False:
            bazoviy_shans = 0.5
            bonus = (m["player2_rating"] - 1000) / 2000
            shans = bazoviy_shans + bonus
            if shans < 0.3:
                shans = 0.3
            if shans > 0.8:
                shans = 0.8

            sluch = _poluchit_sluchainoe_chislo(1, 100) / 100.0
            bot_pravilno = sluch < shans
            bot_time = _poluchit_sluchainoe_chislo(20, 120) / 10.0

            if bot_pravilno:
                bot_answer = zadacha["answer"]
            else:
                nepravilnie = [opt for opt in zadacha["options"] if opt != zadacha["answer"]]
                if len(nepravilnie) > 0:
                    idx = _poluchit_sluchainoe_chislo(0, len(nepravilnie) - 1)
                    bot_answer = nepravilnie[idx]
                else:
                    bot_answer = zadacha["options"][0]

            bot_otvet = {
                "task_index": data.task_index,
                "answer": bot_answer,
                "correct": bot_pravilno,
                "time_spent": bot_time,
                "created_at": time.time(),
                "updated_at": time.time()
            }
            m["player2_answers"].append(bot_otvet)
            update_data["player2_answers"] = m["player2_answers"]

            if bot_pravilno == True:
                update_data["player2_score"] = m["player2_score"] + 1

    db.obnovit_match(data.match_id, **update_data)

    # получаем обновленный матч
    m = db.poluchit_match_po_id(data.match_id)

    return {
        "success": True,
        "correct": pravilno,
        "player1_score": m["player1_score"],
        "player2_score": m["player2_score"],
        "correct_answer": zadacha["answer"]
    }


@app.post("/api/match/next_task/{match_id}")
def sleduushaya_zadacha(match_id: int, user_id: int):
    m = db.poluchit_match_po_id(match_id)

    if m == None:
        raise HTTPException(status_code=404, detail="Матч не найден")

    if m["player1_id"] != user_id and m["player2_id"] != user_id:
        raise HTTPException(status_code=403, detail="Вы не участник матча")

    return {"success": True, "current_task": m["current_task"], "status": m["status"]}


@app.post("/api/match/end")
def zavershit_match(data: MatchEndData):
    m = db.poluchit_match_po_id(data.match_id)

    if m == None:
        raise HTTPException(status_code=404, detail="Матч не найден")

    user = db.poluchit_usera_po_id(data.user_id)
    if user == None:
        raise HTTPException(status_code=404, detail="Юзер не найден")

    if m["player1_id"] == data.user_id:
        ya_player1 = True
        moy_schet = m["player1_score"]
        ego_schet = m["player2_score"]
        ego_reyting = m["player2_rating"]
        ego_imya = m["player2_name"]
        moi_otvety = m.get("player1_answers", [])
    else:
        ya_player1 = False
        moy_schet = m["player2_score"]
        ego_schet = m["player1_score"]
        ego_reyting = m["player1_rating"]
        ego_imya = m["player1_name"]
        moi_otvety = m.get("player2_answers", [])

    if data.result == "cancelled" or data.result == "error":
        rezultat = data.result
    else:
        if moy_schet > ego_schet:
            rezultat = "win"
        elif moy_schet < ego_schet:
            rezultat = "loss"
        else:
            rezultat = "draw"

    izmenenie_reytinga = 0

    if rezultat == "cancelled" or rezultat == "error":
        db.obnovit_match(data.match_id, status=rezultat)
    else:
        db.obnovit_match(data.match_id, status="finished", finished_at=datetime.now().isoformat())

        # расчёт ело для рейтинговых
        if m["mode"] == "ranked":
            izmenenie_reytinga = poschitat_elo(user.get("rating", 1000), ego_reyting, rezultat)
            new_rating = user.get("rating", 1000) + izmenenie_reytinga

            # обновляем рейтинг соперника если не бот
            if m.get("is_bot", False) == False:
                sopernik_id = m["player2_id"] if ya_player1 else m["player1_id"]
                sopernik = db.poluchit_usera_po_id(sopernik_id)

                if sopernik != None:
                    if rezultat == "win":
                        sopernik_rez = "loss"
                    elif rezultat == "loss":
                        sopernik_rez = "win"
                    else:
                        sopernik_rez = "draw"

                    sopernik_izm = poschitat_elo(
                        sopernik.get("rating", 1000),
                        user.get("rating", 1000),
                        sopernik_rez
                    )

                    updates = {"rating": sopernik.get("rating", 1000) + sopernik_izm}
                    if sopernik_rez == "win":
                        updates["wins"] = sopernik.get("wins", 0) + 1
                    elif sopernik_rez == "loss":
                        updates["losses"] = sopernik.get("losses", 0) + 1
                    else:
                        updates["draws"] = sopernik.get("draws", 0) + 1

                    db.obnovit_usera(sopernik_id, **updates)

            db.obnovit_usera(data.user_id, rating=new_rating)

        # статистика
        updates = {}
        if rezultat == "win":
            updates["wins"] = user.get("wins", 0) + 1
        elif rezultat == "loss":
            updates["losses"] = user.get("losses", 0) + 1
        else:
            updates["draws"] = user.get("draws", 0) + 1

        # считаем правильные ответы
        pravilnih = 0
        for o in moi_otvety:
            if o.get("correct", False) == True:
                pravilnih = pravilnih + 1

        updates["solved_count"] = user.get("solved_count", 0) + len(m["tasks"])
        updates["correct_count"] = user.get("correct_count", 0) + pravilnih

        # xp
        zarabotano_xp = moy_schet * 20
        if rezultat == "win":
            zarabotano_xp = zarabotano_xp + 50

        new_xp = user.get("xp", 0) + zarabotano_xp
        new_level = user.get("level", 1)
        xp_dlya_lvla = new_level * 100
        while new_xp >= xp_dlya_lvla:
            new_level = new_level + 1
            xp_dlya_lvla = new_level * 100

        updates["xp"] = new_xp
        updates["level"] = new_level

        db.obnovit_usera(data.user_id, **updates)

        # история матча
        db.dobavit_match_v_istoriyu(
            data.user_id, m["id"], ego_imya, ego_reyting,
            moy_schet, ego_schet, rezultat, izmenenie_reytinga,
            m["subject"], m["mode"]
        )

        # общая история
        zapis = "PvP: " + str(moy_schet) + ":" + str(ego_schet) + " vs " + ego_imya
        db.dobavit_v_istoriyu(data.user_id, zapis)

        # статистика по дням
        db.obnovit_daily_stats(data.user_id, len(m["tasks"]), pravilnih, m["subject"])

        # достижения
        proverit_dostizheniya(data.user_id)

    user = db.poluchit_usera_po_id(data.user_id)
    otvet_user = format_user_for_response(user)

    return {
        "success": True,
        "rating_change": izmenenie_reytinga,
        "result": rezultat,
        "user": otvet_user,
        "match_id": m["id"]
    }


###################################
# API - таблица лидеров
###################################

@app.get("/api/leaderboard")
def poluchit_liderov(limit: int = 10):
    usery = db.poluchit_vseh_userov()

    # сортируем по рейтингу
    otsortirovannie = moya_sortirovka_po_polyu(usery, "rating", po_vozrastaniyu=False)

    rezultat = []
    i = 0
    while i < limit and i < len(otsortirovannie):
        u = otsortirovannie[i]
        zapis = {
            "rank": i + 1,
            "id": u["id"],
            "name": u.get("name") or u.get("username"),
            "rating": u.get("rating", 1000),
            "level": u.get("level", 1),
            "wins": u.get("stats", {}).get("wins", 0) or u.get("wins", 0)
        }
        rezultat.append(zapis)
        i = i + 1

    return rezultat


###################################
# API - админка
###################################

@app.get("/api/admin/users")
def admin_poluchit_userov():
    usery = db.poluchit_vseh_userov()

    rezultat = []
    for u in usery:
        zapis = {
            "id": u["id"],
            "name": u.get("name") or u.get("username"),
            "email": u.get("email"),
            "isAdmin": u.get("isAdmin", False) or u.get("is_admin", 0) == 1,
            "level": u.get("level", 1),
            "rating": u.get("rating", 1000),
            "solved": u.get("stats", {}).get("solved", 0) or u.get("solved_count", 0)
        }
        rezultat.append(zapis)

    return rezultat


@app.post("/api/admin/tasks/import")
async def importirovat_zadachi(request: Request):
    data = await request.json()
    importiruemie = data.get("tasks", [])
    skolko = 0

    for task in importiruemie:
        db.sozdat_zadachu(
            task.get("subject", ""),
            task.get("difficulty", "medium"),
            task.get("topic", ""),
            task.get("question", ""),
            task.get("options", []),
            task.get("answer", ""),
            task.get("hint", "")
        )
        skolko = skolko + 1

    return {"success": True, "imported": skolko}


@app.get("/api/admin/tasks/export")
def eksportirovat_zadachi():
    taski = db.poluchit_vse_zadachi()
    return {"tasks": taski, "count": len(taski)}


@app.post("/api/admin/generate")
def generirovat_zadachi(subject: str, difficulty: str, count: int):
    sgenerirovannie = []

    i = 0
    while i < count:
        if subject == "math":
            a = _poluchit_sluchainoe_chislo(10, 99)
            b = _poluchit_sluchainoe_chislo(10, 99)

            if difficulty == "easy":
                otvet = a + b
                vopros = "Сколько будет " + str(a) + " + " + str(b) + "?"
            elif difficulty == "medium":
                otvet = a * b
                vopros = "Вычисли: " + str(a) + " × " + str(b)
            else:
                otvet = a * a + b
                vopros = "Найди: " + str(a) + "² + " + str(b)

            var1 = otvet + _poluchit_sluchainoe_chislo(1, 10)
            var2 = otvet - _poluchit_sluchainoe_chislo(1, 10)
            var3 = otvet + _poluchit_sluchainoe_chislo(11, 20)

            varianti = [str(otvet), str(var1), str(var2), str(var3)]
            varianti = moy_shuffle(varianti)

            task_id = db.sozdat_zadachu(
                subject, difficulty, "Сгенерировано",
                vopros, varianti, str(otvet), "Посчитай внимательно"
            )
        else:
            varianti = ["Ответ A", "Ответ B", "Ответ C", "Ответ D"]
            task_id = db.sozdat_zadachu(
                subject, difficulty, "Сгенерировано",
                "Вопрос #" + str(i + 1) + " по " + subject,
                varianti, "Ответ A", "Подумай хорошенько"
            )

        novaya = db.poluchit_zadachu_po_id(task_id)
        sgenerirovannie.append(novaya)
        i = i + 1

    return {"success": True, "generated": len(sgenerirovannie)}


###################################
# главная страница
###################################

@app.get("/", response_class=HTMLResponse)
def glavnaya():
    if os.path.exists("index.html"):
        f = open("index.html", "r", encoding="utf-8")
        soderzhimoe = f.read()
        f.close()
        return soderzhimoe
    return "<h1>EduBattle</h1><p>Положи index.html в папку с сервером</p>"


# запуск
if __name__ == "__main__":
    import uvicorn

    # проверяем базу
    if db.proverit_bazu() == False:
        print("ОШИБКА: база данных не найдена!")
        print("Сначала запусти: python database.py")
        exit(1)

    print("=" * 50)
    print("EduBattle Server v3.0")
    print("теперь с базой данных SQLite!")
    print("=" * 50)
    print("Открой http://localhost:8000")
    print("Админ: admin@edu.ru / admin123")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
