# -*- coding: utf-8 -*-
# EduBattle сервер v3.2
# + Активный heartbeat механизм
# + Мгновенная отмена при отключении

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

import db_helper as db

app = FastAPI(title="EduBattle")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

###################################
# КОНСТАНТЫ
###################################

# интервал heartbeat опроса (секунды)
HEARTBEAT_INTERVAL = 10

# максимальное время без ответа до отмены (секунды)
MAX_NO_RESPONSE_TIME = 15

# время ожидания pong после ping (секунды)
PONG_TIMEOUT = 5

###################################
# генератор id и сортировки
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
# WebSocket менеджер с активным
# heartbeat опросом
###################################

class MoyWebSocketManager:
    def __init__(self):
        # match_id -> список вебсокетов
        self.aktivnie_sockety: Dict[int, List[WebSocket]] = {}

        # user_id -> вебсокет
        self.user_sockety: Dict[int, WebSocket] = {}

        # user_id -> match_id
        self.user_match: Dict[int, int] = {}

        # user_id -> время последнего ответа (pong или любое сообщение)
        self.poslednie_otkliki: Dict[int, float] = {}

        # user_id -> ожидаем pong (True если отправили ping и ждём ответ)
        self.ozhidaem_pong: Dict[int, bool] = {}

        # user_id -> время отправки ping
        self.vremya_ping: Dict[int, float] = {}

        # match_id -> время последней активности
        self.match_activity: Dict[int, float] = {}

        # очередь сообщений для офлайн юзеров
        self.ochered_soobsheniy: Dict[int, List[dict]] = {}

        # заблокированные матчи (уже отменяются)
        self.cancelling_matches: set = set()

    async def podkluchit(self, websocket: WebSocket, match_id: int, user_id: int):
        await websocket.accept()

        if match_id not in self.aktivnie_sockety:
            self.aktivnie_sockety[match_id] = []

        self.aktivnie_sockety[match_id].append(websocket)
        self.user_sockety[user_id] = websocket
        self.user_match[user_id] = match_id

        # Фиксируем время подключения как последний отклик
        self.poslednie_otkliki[user_id] = time.time()
        self.ozhidaem_pong[user_id] = False
        self.match_activity[match_id] = time.time()

        print(f"[WS CONNECT] user {user_id} подключился к матчу {match_id}")

        # Отправляем накопленные сообщения
        if user_id in self.ochered_soobsheniy:
            for msg in self.ochered_soobsheniy[user_id]:
                try:
                    await websocket.send_json(msg)
                except:
                    pass
            self.ochered_soobsheniy[user_id] = []

        # Уведомляем остальных о подключении
        await self.otpravit_v_match(match_id, {
            "type": "user_connected",
            "user_id": user_id,
            "time": time.time()
        })

    def otkluchit(self, websocket: WebSocket, match_id: int, user_id: int):
        """Удаляет пользователя из активных соединений"""

        if match_id in self.aktivnie_sockety:
            noviy_spisok = []
            for ws in self.aktivnie_sockety[match_id]:
                if ws != websocket:
                    noviy_spisok.append(ws)
            self.aktivnie_sockety[match_id] = noviy_spisok

            if len(self.aktivnie_sockety[match_id]) == 0:
                del self.aktivnie_sockety[match_id]

        if user_id in self.user_sockety:
            del self.user_sockety[user_id]
        if user_id in self.user_match:
            del self.user_match[user_id]
        if user_id in self.poslednie_otkliki:
            del self.poslednie_otkliki[user_id]
        if user_id in self.ozhidaem_pong:
            del self.ozhidaem_pong[user_id]
        if user_id in self.vremya_ping:
            del self.vremya_ping[user_id]

        print(f"[WS DISCONNECT] user {user_id} отключился")

    def zaregistrirovat_otklik(self, user_id: int):
        """Регистрирует любую активность пользователя"""
        self.poslednie_otkliki[user_id] = time.time()
        self.ozhidaem_pong[user_id] = False

        if user_id in self.user_match:
            match_id = self.user_match[user_id]
            self.match_activity[match_id] = time.time()

    async def otpravit_ping(self, user_id: int) -> bool:
        """Отправляет ping пользователю. Возвращает True если отправлено."""
        if user_id not in self.user_sockety:
            return False

        try:
            await self.user_sockety[user_id].send_json({
                "type": "server_ping",
                "timestamp": time.time()
            })
            self.ozhidaem_pong[user_id] = True
            self.vremya_ping[user_id] = time.time()
            return True
        except Exception as e:
            print(f"[PING ERROR] user {user_id}: {e}")
            return False

    def proverit_zhiv_li(self, user_id: int) -> bool:
        """Проверяет жив ли пользователь по времени последнего отклика"""
        if user_id not in self.poslednie_otkliki:
            return False

        vremya_bez_otklika = time.time() - self.poslednie_otkliki[user_id]
        return vremya_bez_otklika < MAX_NO_RESPONSE_TIME

    def poluchit_userov_v_matche(self, match_id: int) -> List[int]:
        """Возвращает список user_id в матче"""
        result = []
        for user_id, mid in self.user_match.items():
            if mid == match_id:
                result.append(user_id)
        return result

    async def otpravit_v_match(self, match_id: int, soobshenie: dict):
        if match_id in self.aktivnie_sockety:
            sockety = self.aktivnie_sockety[match_id]
            for ws in sockety:
                try:
                    await ws.send_json(soobshenie)
                except Exception as e:
                    print(f"[SEND ERROR] {e}")

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


ws_manager = MoyWebSocketManager()


###################################
# Фоновая задача HEARTBEAT
# Опрашивает клиентов каждые 10 сек
###################################

async def heartbeat_loop():
    """
    Главный цикл проверки соединений.
    Каждые HEARTBEAT_INTERVAL секунд:
    1. Отправляет ping всем подключенным
    2. Проверяет кто не ответил
    3. Отменяет матчи с отключенными игроками
    """
    print("[HEARTBEAT] Запущен цикл проверки соединений")

    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)

            current_time = time.time()

            # Получаем список всех активных матчей
            aktivnie_matchi = set()
            for user_id, match_id in list(ws_manager.user_match.items()):
                aktivnie_matchi.add(match_id)

            # Для каждого матча проверяем игроков
            for match_id in aktivnie_matchi:

                # Пропускаем если матч уже отменяется
                if match_id in ws_manager.cancelling_matches:
                    continue

                # Получаем матч из базы
                m = db.poluchit_match_po_id(match_id)
                if m is None or m["status"] != "active":
                    continue

                # Получаем игроков матча
                player1_id = m["player1_id"]
                player2_id = m["player2_id"]

                # Проверяем каждого игрока (кроме бота)
                players_to_check = []
                if player1_id and player1_id != 0:
                    players_to_check.append((player1_id, m["player1_name"]))
                if player2_id and player2_id != 0 and m.get("is_bot", False) == False:
                    players_to_check.append((player2_id, m["player2_name"]))

                for player_id, player_name in players_to_check:

                    # Проверяем подключен ли игрок
                    if player_id not in ws_manager.user_sockety:
                        # Игрок не подключен - отменяем матч
                        print(f"[HEARTBEAT] user {player_id} не подключен к матчу {match_id}")
                        await otmenit_match_iz_za_otklyucheniya(match_id, player_id, player_name)
                        break

                    # Проверяем время последнего отклика
                    if player_id in ws_manager.poslednie_otkliki:
                        vremya_bez_otklika = current_time - ws_manager.poslednie_otkliki[player_id]

                        if vremya_bez_otklika > MAX_NO_RESPONSE_TIME:
                            # Слишком долго без ответа - отменяем матч
                            print(f"[HEARTBEAT] user {player_id} не отвечает {vremya_bez_otklika:.1f}s")
                            await otmenit_match_iz_za_otklyucheniya(match_id, player_id, player_name)
                            break

                    # Отправляем ping
                    ping_sent = await ws_manager.otpravit_ping(player_id)
                    if not ping_sent:
                        # Не удалось отправить ping - соединение потеряно
                        print(f"[HEARTBEAT] не удалось отправить ping user {player_id}")
                        await otmenit_match_iz_za_otklyucheniya(match_id, player_id, player_name)
                        break

        except Exception as e:
            print(f"[HEARTBEAT ERROR] {e}")


async def otmenit_match_iz_za_otklyucheniya(match_id: int, disconnected_user_id: int, disconnected_name: str):
    """
    Немедленно отменяет матч из-за отключения игрока.
    Рейтинги НЕ изменяются.
    """

    # Защита от повторной отмены
    if match_id in ws_manager.cancelling_matches:
        return
    ws_manager.cancelling_matches.add(match_id)

    try:
        m = db.poluchit_match_po_id(match_id)
        if m is None or m["status"] != "active":
            return

        print(f"[MATCH CANCEL] Отмена матча {match_id} - игрок {disconnected_name} отключился")

        # Обновляем статус матча в базе
        db.obnovit_match(
            match_id,
            status="cancelled",
            cancel_reason="player_disconnected",
            cancelled_by=disconnected_user_id,
            cancelled_at=datetime.now().isoformat()
        )

        # Уведомляем всех в матче
        await ws_manager.otpravit_v_match(match_id, {
            "type": "match_cancelled",
            "reason": "player_disconnected",
            "disconnected_user_id": disconnected_user_id,
            "disconnected_name": disconnected_name,
            "message": f"Матч отменён: игрок {disconnected_name} потерял соединение",
            "rating_changed": False,
            "time": time.time()
        })

        # Добавляем в историю
        zapis = f"Матч отменён: {disconnected_name} отключился"
        if m["player1_id"] and m["player1_id"] != disconnected_user_id:
            db.dobavit_v_istoriyu(m["player1_id"], zapis)
        if m["player2_id"] and m["player2_id"] != 0 and m["player2_id"] != disconnected_user_id:
            db.dobavit_v_istoriyu(m["player2_id"], zapis)

    finally:
        # Убираем из списка отменяющихся через некоторое время
        await asyncio.sleep(5)
        ws_manager.cancelling_matches.discard(match_id)


@app.on_event("startup")
async def startup_event():
    """Запуск фоновых задач при старте сервера"""
    asyncio.create_task(heartbeat_loop())
    print("[STARTUP] Сервер запущен, heartbeat активен")


###################################
# вспомогательные функции
###################################

def zashifrovat_parol(parol):
    sol = "moy_secret_sol_2024"
    vmeste = parol + sol
    hesh = hashlib.sha256(vmeste.encode()).hexdigest()
    return hesh


def proverit_dostizheniya(user_id):
    user = db.poluchit_usera_po_id(user_id)
    if user == None:
        return []

    novie = []
    tekushie_achi = user.get("achievements", [])
    stats = user.get("stats", {})

    if "first_task" not in tekushie_achi:
        if stats.get("solved", 0) >= 1:
            db.dobavit_dostizhenie(user_id, "first_task")
            db.obnovit_usera(user_id, xp=user.get("xp", 0) + 10)
            novie.append({"id": "first_task", "name": "Первый шаг", "xp": 10})

    if "ten_tasks" not in tekushie_achi:
        if stats.get("solved", 0) >= 10:
            db.dobavit_dostizhenie(user_id, "ten_tasks")
            db.obnovit_usera(user_id, xp=user.get("xp", 0) + 50)
            novie.append({"id": "ten_tasks", "name": "Начинающий", "xp": 50})

    if "fifty_tasks" not in tekushie_achi:
        if stats.get("solved", 0) >= 50:
            db.dobavit_dostizhenie(user_id, "fifty_tasks")
            db.obnovit_usera(user_id, xp=user.get("xp", 0) + 200)
            novie.append({"id": "fifty_tasks", "name": "Упорный", "xp": 200})

    if "first_win" not in tekushie_achi:
        if stats.get("wins", 0) >= 1:
            db.dobavit_dostizhenie(user_id, "first_win")
            db.obnovit_usera(user_id, xp=user.get("xp", 0) + 100)
            novie.append({"id": "first_win", "name": "Победитель", "xp": 100})

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
    if user == None:
        return None

    otvet = {
        "id": user.get("id"),
        "name": user.get("name") or user.get("username"),
        "email": user.get("email"),
        "isAdmin": user.get("isAdmin", False) or user.get("is_admin", 0) == 1,
        "isBanned": user.get("is_active", 1) == 0,  # ДОБАВЛЕНО
        "level": user.get("level", 1),
        "xp": user.get("xp", 0),
        "rating": user.get("rating", 1000),
        "stats": user.get("stats", {"solved": 0, "correct": 0, "wins": 0, "losses": 0, "draws": 0}),
        "achievements": user.get("achievements", []),
        "subjectStats": user.get("subjectStats", {}),
    }

    history = db.poluchit_istoriyu(user["id"], 50)
    otvet["history"] = []
    if history != None:
        for h in history:
            otvet["history"].append({
                "text": h.get("action_text", ""),
                "date": h.get("action_date", ""),
                "timestamp": h.get("created_at", 0)
            })

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


def match_otmenen(status):
    """Проверяет отменён ли матч"""
    return status in ["cancelled", "technical_error", "player_disconnected", "timeout"]


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

class EventCreate(BaseModel):
    name: str
    description: str = ""
    type: str  # 'marathon' или 'tournament'
    start_time: str
    end_time: str
    rules: dict
    max_participants: int = 100
    prizes: dict = {}


class EventJoin(BaseModel):
    user_id: int

class BanData(BaseModel):
    admin_id: int
    reason: str = ""

###################################
# WebSocket эндпоинт
###################################

@app.websocket("/ws/match/{match_id}/{user_id}")
async def websocket_match(websocket: WebSocket, match_id: int, user_id: int):
    if db.proverit_ban(user_id):
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "message": "Ваш аккаунт заблокирован",
            "code": "BANNED"
        })
        await websocket.close(code=4003)
        return

    await ws_manager.podkluchit(websocket, match_id, user_id)

    try:
        while True:
            data = await websocket.receive_json()
            tip = data.get("type", "")

            # Любое сообщение = пользователь жив
            ws_manager.zaregistrirovat_otklik(user_id)

            if tip == "ping":
                await websocket.send_json({"type": "pong", "time": time.time()})

            elif tip == "pong" or tip == "server_pong":
                # Ответ на наш server_ping
                pass  # уже зарегистрировали отклик выше

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
        print(f"[WS] WebSocketDisconnect от user {user_id}")
        ws_manager.otkluchit(websocket, match_id, user_id)

        # Немедленно проверяем и отменяем матч
        m = db.poluchit_match_po_id(match_id)
        if m and m["status"] == "active":
            user = db.poluchit_usera_po_id(user_id)
            user_name = user.get("name", "Игрок") if user else "Игрок"
            await otmenit_match_iz_za_otklyucheniya(match_id, user_id, user_name)

    except Exception as e:
        print(f"[WS ERROR] user {user_id}: {e}")
        ws_manager.otkluchit(websocket, match_id, user_id)

        # Отменяем матч при любой ошибке
        m = db.poluchit_match_po_id(match_id)
        if m and m["status"] == "active":
            user = db.poluchit_usera_po_id(user_id)
            user_name = user.get("name", "Игрок") if user else "Игрок"
            await otmenit_match_iz_za_otklyucheniya(match_id, user_id, user_name)


async def obrabota_otvet_ws(data, match_id, user_id):
    """Обработка ответа с поддержкой повторной отправки"""

    m = db.poluchit_match_po_id(match_id)

    if m == None:
        return {"type": "error", "message": "матч не найден"}

    if match_otmenen(m["status"]):
        return {"type": "error", "message": "матч отменён", "status": m["status"]}

    if m["status"] != "active":
        return {"type": "error", "message": "матч не активен"}

    task_index = data.get("task_index", 0)
    answer = data.get("answer", "")
    time_spent = data.get("time_spent", 0)

    if task_index < 0 or task_index >= len(m["tasks"]):
        return {"type": "error", "message": "неверный индекс задачи"}

    zadacha = m["tasks"][task_index]
    pravilno = answer == zadacha["answer"]

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

    # Ищем предыдущий ответ на эту задачу
    uzhe_otvetil = False
    j = 0
    while j < len(otvety):
        if otvety[j]["task_index"] == task_index:
            uzhe_otvetil = True
            # Если предыдущий был правильный - вычитаем балл
            if otvety[j]["correct"] == True:
                schet = schet - 1
            # Заменяем ответ
            otvety[j]["answer"] = answer
            otvety[j]["correct"] = pravilno
            otvety[j]["time_spent"] = time_spent
            otvety[j]["updated_at"] = time.time()
            otvety[j]["attempts"] = otvety[j].get("attempts", 1) + 1
            break
        j = j + 1

    if uzhe_otvetil == False:
        noviy_otvet = {
            "task_index": task_index,
            "answer": answer,
            "correct": pravilno,
            "time_spent": time_spent,
            "created_at": time.time(),
            "updated_at": time.time(),
            "attempts": 1
        }
        otvety.append(noviy_otvet)

    if pravilno == True:
        schet = schet + 1

    update_data = {otvety_key: otvety, schet_key: schet}

    # Бот
    if m.get("is_bot", False) == True and m["player2_id"] == 0:
        bot_otvetil = False
        for o in m["player2_answers"]:
            if o["task_index"] == task_index:
                bot_otvetil = True
                break

        if bot_otvetil == False:
            shans = 0.5 + (m["player2_rating"] - 1000) / 2000
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
                nepravilnie = [opt for opt in zadacha["options"] if opt != zadacha["answer"]]
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
                "updated_at": time.time(),
                "attempts": 1
            }
            m["player2_answers"].append(bot_otvet)
            update_data["player2_answers"] = m["player2_answers"]

            if bot_pravilno == True:
                update_data["player2_score"] = m["player2_score"] + 1

    db.obnovit_match(match_id, **update_data)
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
        "was_resubmit": uzhe_otvetil,
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
        "is_cancelled": match_otmenen(m["status"]),
        "cancel_reason": m.get("cancel_reason"),
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

    # ПРОВЕРКА БАНА
    if user.get("is_active", 1) == 0:
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован. Обратитесь к администратору.")

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

    if match_otmenen(m["status"]):
        rezultat = "cancelled"
    elif moy_schet > ego_schet:
        rezultat = "win"
    elif moy_schet < ego_schet:
        rezultat = "loss"
    else:
        rezultat = "draw"

    obshaya_stat = {
        "match_id": m["id"],
        "status": m["status"],
        "is_cancelled": match_otmenen(m["status"]),
        "cancel_reason": m.get("cancel_reason"),
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

            if match_otmenen(m["status"]):
                rezultat = "cancelled"
            elif moy_schet > ego_schet:
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

    new_solved = user.get("solved_count", 0) + data.tasks_solved
    new_correct = user.get("correct_count", 0) + data.correct_count
    new_xp = user.get("xp", 0) + data.xp_earned
    new_level = user.get("level", 1)

    xp_dlya_lvla = new_level * 100
    while new_xp >= xp_dlya_lvla:
        new_level = new_level + 1
        xp_dlya_lvla = new_level * 100

    subject_stats = user.get("subjectStats", {})
    if data.subject not in subject_stats:
        subject_stats[data.subject] = {"solved": 0, "correct": 0}
    subject_stats[data.subject]["solved"] = subject_stats[data.subject]["solved"] + data.tasks_solved
    subject_stats[data.subject]["correct"] = subject_stats[data.subject]["correct"] + data.correct_count

    db.obnovit_usera(data.user_id,
                     solved_count=new_solved,
                     correct_count=new_correct,
                     xp=new_xp,
                     level=new_level,
                     subject_stats=json.dumps(subject_stats)
                     )

    zapis = "Тренировка: " + str(data.correct_count) + "/" + str(data.tasks_solved)
    db.dobavit_v_istoriyu(data.user_id, zapis)

    db.obnovit_daily_stats(data.user_id, data.tasks_solved, data.correct_count, data.subject)

    novie_achi = proverit_dostizheniya(data.user_id)

    user = db.poluchit_usera_po_id(data.user_id)
    otvet = format_user_for_response(user)
    active_marathons = db.poluchit_aktivnie_eventi_usera(data.user_id, "marathon")
    for marathon in active_marathons:
        rules = marathon.get("rules", {})
        subjects = rules.get("subjects", [])

        # Проверяем подходит ли предмет
        if "all" in subjects or data.subject in subjects:
            scoring = rules.get("scoring", {})
            points_per_task = scoring.get("training_task", 10)
            total_points = points_per_task * data.correct_count

            # Обновляем очки
            db.obnovit_score_eventa(
                marathon["id"],
                data.user_id,
                total_points,
                tasks_solved=data.tasks_solved,
                tasks_correct=data.correct_count
            )

            # Записываем активность
            db.dobavit_aktivnost_marafona(
                marathon["id"],
                data.user_id,
                "training",
                total_points,
                {
                    "subject": data.subject,
                    "solved": data.tasks_solved,
                    "correct": data.correct_count
                }
            )

    return {"success": True, "user": otvet, "new_achievements": novie_achi}


###################################
# API - PvP матчи
###################################

@app.post("/api/match/search")
def iskat_match(data: MatchSearchData):
    user = db.poluchit_usera_po_id(data.user_id)
    if user == None:
        raise HTTPException(status_code=404, detail="Юзер не найден")

    if db.proverit_ban(data.user_id):
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован")

    poziciya = db.poluchit_poziciyu_v_ocheredi(data.user_id)
    if poziciya >= 0:
        ochered = db.poluchit_ochered()
        return {"status": "waiting", "queue_id": ochered[poziciya]["id"], "position": poziciya + 1}

    aktivnie = db.poluchit_aktivnie_matchi_usera(data.user_id)
    if len(aktivnie) > 0:
        return {"status": "in_match", "match_id": aktivnie[0]["id"]}

    sopernik_v_ocheredi = db.nayti_sopernika_v_ocheredi(
        data.user_id, user.get("rating", 1000), data.subject, data.mode
    )

    if sopernik_v_ocheredi != None:
        sopernik = db.poluchit_usera_po_id(sopernik_v_ocheredi["user_id"])

        db.ubrat_iz_ocheredi(sopernik_v_ocheredi["user_id"])

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
    aktivnie = db.poluchit_aktivnie_matchi_usera(user_id)
    if len(aktivnie) > 0:
        return {"status": "matched", "match": aktivnie[0]}

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

    if db.proverit_ban(data.user_id):
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован")

    db.ubrat_iz_ocheredi(data.user_id)

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

    bot_imena = ["Умник_2024", "MathPro", "Знайка", "Эрудит", "BrainMaster", "Гений99", "SmartBot", "Quiz_Master"]
    bot_idx = _poluchit_sluchainoe_chislo(0, len(bot_imena) - 1)
    bot_imya = bot_imena[bot_idx]
    bot_reyting = user.get("rating", 1000) + _poluchit_sluchainoe_chislo(-100, 100)

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
        "is_cancelled": match_otmenen(m["status"]),
        "cancel_reason": m.get("cancel_reason"),
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

    if match_otmenen(m["status"]):
        raise HTTPException(status_code=400, detail=f"Матч отменён: {m['status']}")

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

    # Проверяем повторную отправку
    predidushiy = None
    was_resubmit = False
    j = 0
    while j < len(otvety):
        if otvety[j]["task_index"] == data.task_index:
            predidushiy = otvety[j]
            was_resubmit = True
            break
        j = j + 1

    if predidushiy != None:
        if predidushiy["correct"] == True:
            schet = schet - 1
        predidushiy["answer"] = data.answer
        predidushiy["correct"] = pravilno
        predidushiy["time_spent"] = data.time_spent
        predidushiy["updated_at"] = time.time()
        predidushiy["attempts"] = predidushiy.get("attempts", 1) + 1
    else:
        noviy_otvet = {
            "task_index": data.task_index,
            "answer": data.answer,
            "correct": pravilno,
            "time_spent": data.time_spent,
            "created_at": time.time(),
            "updated_at": time.time(),
            "attempts": 1
        }
        otvety.append(noviy_otvet)

    if pravilno == True:
        schet = schet + 1

    update_data = {otvety_key: otvety, schet_key: schet}

    # Бот
    if m.get("is_bot", False) == True and m["player2_id"] == 0:
        bot_otvetil = False
        for o in m["player2_answers"]:
            if o["task_index"] == data.task_index:
                bot_otvetil = True
                break

        if bot_otvetil == False:
            shans = 0.5 + (m["player2_rating"] - 1000) / 2000
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
                "updated_at": time.time(),
                "attempts": 1
            }
            m["player2_answers"].append(bot_otvet)
            update_data["player2_answers"] = m["player2_answers"]

            if bot_pravilno == True:
                update_data["player2_score"] = m["player2_score"] + 1

    db.obnovit_match(data.match_id, **update_data)

    m = db.poluchit_match_po_id(data.match_id)

    return {
        "success": True,
        "correct": pravilno,
        "player1_score": m["player1_score"],
        "player2_score": m["player2_score"],
        "correct_answer": zadacha["answer"],
        "was_resubmit": was_resubmit
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

    # Проверяем не отменён ли уже матч
    if match_otmenen(m["status"]):
        return {
            "success": True,
            "rating_change": 0,
            "result": "cancelled",
            "user": format_user_for_response(user),
            "match_id": m["id"],
            "is_cancelled": True,
            "cancel_reason": m.get("cancel_reason")
        }

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

    # Проверяем запрос на отмену
    if data.result == "cancelled" or data.result == "error":
        db.obnovit_match(data.match_id, status="cancelled", cancel_reason=data.result)
        return {
            "success": True,
            "rating_change": 0,
            "result": "cancelled",
            "user": format_user_for_response(user),
            "match_id": m["id"],
            "is_cancelled": True
        }

    # Нормальное завершение
    if moy_schet > ego_schet:
        rezultat = "win"
    elif moy_schet < ego_schet:
        rezultat = "loss"
    else:
        rezultat = "draw"

    izmenenie_reytinga = 0

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

    pravilnih = 0
    for o in moi_otvety:
        if o.get("correct", False) == True:
            pravilnih = pravilnih + 1

    updates["solved_count"] = user.get("solved_count", 0) + len(m["tasks"])
    updates["correct_count"] = user.get("correct_count", 0) + pravilnih

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

    db.dobavit_match_v_istoriyu(
        data.user_id, m["id"], ego_imya, ego_reyting,
        moy_schet, ego_schet, rezultat, izmenenie_reytinga,
        m["subject"], m["mode"]
    )

    zapis = "PvP: " + str(moy_schet) + ":" + str(ego_schet) + " vs " + ego_imya
    db.dobavit_v_istoriyu(data.user_id, zapis)

    db.obnovit_daily_stats(data.user_id, len(m["tasks"]), pravilnih, m["subject"])

    proverit_dostizheniya(data.user_id)
    if m.get("event_id"):
        event = db.poluchit_event_po_id(m["event_id"])

        if event and event["type"] == "tournament":
            tournament_match = db.poluchit_match_turnira_po_match_id(data.match_id)

            if tournament_match:
                # Определяем победителя
                winner_id = None
                if rezultat == "win":
                    winner_id = data.user_id
                elif rezultat == "loss":
                    winner_id = m["player2_id"] if m["player1_id"] == data.user_id else m["player1_id"]

                # Обновляем матч турнира
                db.obnovit_match_turnira(tournament_match["id"], winner_id=winner_id, status="finished")

                # Начисляем турнирные очки
                points_config = event["rules"].get("points", {"win": 3, "draw": 1, "loss": 0})
                points = points_config.get(rezultat, 0)

                db.obnovit_score_eventa(m["event_id"], data.user_id, points)
                db.obnovit_match_stats_eventa(m["event_id"], data.user_id, rezultat == "win")

    # Обновляем марафоны
    active_marathons = db.poluchit_aktivnie_eventi_usera(data.user_id, "marathon")
    for marathon in active_marathons:
        rules = marathon.get("rules", {})
        subjects = rules.get("subjects", [])

        if "all" in subjects or m["subject"] in subjects:
            scoring = rules.get("scoring", {})

            if rezultat == "win":
                points = scoring.get("pvp_win", 50)
            elif rezultat == "draw":
                points = scoring.get("pvp_draw", 20)
            else:
                points = scoring.get("pvp_loss", 5)

            db.obnovit_score_eventa(marathon["id"], data.user_id, points)
            db.obnovit_match_stats_eventa(marathon["id"], data.user_id, rezultat == "win")

            db.dobavit_aktivnost_marafona(
                marathon["id"],
                data.user_id,
                "pvp_" + rezultat,
                points,
                {
                    "opponent": ego_imya,
                    "score": str(moy_schet) + ":" + str(ego_schet)
                }
            )
    user = db.poluchit_usera_po_id(data.user_id)
    otvet_user = format_user_for_response(user)

    if m.get("event_id"):
        event = db.poluchit_event_po_id(m["event_id"])

        if event and event["type"] == "tournament":
            tournament_match = db.poluchit_match_turnira_po_match_id(data.match_id)

            if tournament_match:
                # Определяем победителя
                winner_id = None
                if rezultat == "win":
                    winner_id = data.user_id
                elif rezultat == "loss":
                    winner_id = m["player2_id"] if m["player1_id"] == data.user_id else m["player1_id"]

                # Обновляем матч турнира
                db.obnovit_match_turnira(tournament_match["id"], winner_id=winner_id, status="finished")

                # Начисляем турнирные очки
                points_config = event["rules"].get("points", {"win": 3, "draw": 1, "loss": 0})
                points = points_config.get(rezultat, 0)

                db.obnovit_score_eventa(m["event_id"], data.user_id, points)
                db.obnovit_match_stats_eventa(m["event_id"], data.user_id, rezultat == "win")

    return {
        "success": True,
        "rating_change": izmenenie_reytinga,
        "result": rezultat,
        "user": otvet_user,
        "match_id": m["id"],
        "is_cancelled": False
    }


###################################
# API - таблица лидеров
###################################

@app.get("/api/leaderboard")
def poluchit_liderov(limit: int = 10):
    usery = db.poluchit_vseh_userov()

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
            "isBanned": u.get("is_active", 1) == 0,  # ДОБАВЛЕНО
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


@app.get("/api/events")
def poluchit_eventi(status: str = None):
    """Получить список событий"""
    # Сначала обновляем статусы
    db.obnovit_status_eventov()

    if status:
        events = db.poluchit_vse_eventi(status)
    else:
        events = db.poluchit_aktivnie_eventi()

    return {"events": events}


@app.get("/api/events/{event_id}")
def poluchit_event(event_id: int):
    """Получить детали события"""
    event = db.poluchit_event_po_id(event_id)

    if event is None:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    return event


@app.post("/api/events")
def sozdat_event(event: EventCreate, user_id: int):
    """Создать новое событие (только для админов)"""
    user = db.poluchit_usera_po_id(user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.get("isAdmin", False) == False and user.get("is_admin", 0) != 1:
        raise HTTPException(status_code=403, detail="Только для администраторов")

    event_id = db.sozdat_event(
        event.name,
        event.description,
        event.type,
        event.start_time,
        event.end_time,
        event.rules,
        event.max_participants,
        event.prizes,
        user_id
    )

    return {"success": True, "event_id": event_id}


@app.post("/api/events/{event_id}/join")
def prisoedinitsya_k_eventu(event_id: int, data: EventJoin):
    """Присоединиться к событию"""
    event = db.poluchit_event_po_id(event_id)

    if event is None:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    if event["status"] == "finished":
        raise HTTPException(status_code=400, detail="Событие уже завершено")

    if event["current_participants"] >= event["max_participants"]:
        raise HTTPException(status_code=400, detail="Достигнут лимит участников")

    # Проверяем минимальный уровень
    user = db.poluchit_usera_po_id(data.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    min_level = event["rules"].get("min_level", 1)
    if user.get("level", 1) < min_level:
        raise HTTPException(status_code=400, detail=f"Требуется уровень {min_level} или выше")

    # Проверяем, не участвует ли уже
    existing = db.poluchit_uchastie_usera(event_id, data.user_id)
    if existing:
        raise HTTPException(status_code=400, detail="Вы уже участвуете в этом событии")

    db.dobavit_uchastnika_eventa(event_id, data.user_id)

    return {"success": True, "message": "Вы успешно присоединились к событию"}


@app.post("/api/events/{event_id}/leave")
def pokinut_event(event_id: int, data: EventJoin):
    """Покинуть событие"""
    event = db.poluchit_event_po_id(event_id)

    if event is None:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    if event["status"] == "active" and event["type"] == "tournament":
        raise HTTPException(status_code=400, detail="Нельзя покинуть активный турнир")

    db.ubrat_uchastnika_eventa(event_id, data.user_id)

    return {"success": True}


@app.get("/api/events/{event_id}/leaderboard")
def poluchit_liderov_eventa(event_id: int, limit: int = 50):
    """Получить таблицу лидеров события"""
    event = db.poluchit_event_po_id(event_id)

    if event is None:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    participants = db.poluchit_uchastnikov_eventa(event_id, limit)

    # Добавляем ранги
    leaderboard = []
    rank = 1
    for p in participants:
        leaderboard.append({
            "rank": rank,
            "user_id": p["user_id"],
            "username": p.get("username", "Участник"),
            "score": p["score"],
            "tasks_solved": p["tasks_solved"],
            "tasks_correct": p["tasks_correct"],
            "matches_played": p["matches_played"],
            "matches_won": p["matches_won"],
            "level": p.get("level", 1),
            "rating": p.get("rating", 1000)
        })
        rank = rank + 1

    return {"leaderboard": leaderboard, "event": event}


@app.get("/api/events/{event_id}/my_status")
def poluchit_moy_status_v_evente(event_id: int, user_id: int):
    """Получить статус участия пользователя в событии"""
    event = db.poluchit_event_po_id(event_id)

    if event is None:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    participation = db.poluchit_uchastie_usera(event_id, user_id)

    if participation is None:
        return {"participating": False, "event": event}

    # Вычисляем ранг
    all_participants = db.poluchit_uchastnikov_eventa(event_id, 1000)
    my_rank = 1
    for p in all_participants:
        if p["user_id"] == user_id:
            break
        my_rank = my_rank + 1

    return {
        "participating": True,
        "event": event,
        "my_stats": {
            "rank": my_rank,
            "score": participation["score"],
            "tasks_solved": participation["tasks_solved"],
            "tasks_correct": participation["tasks_correct"],
            "matches_played": participation["matches_played"],
            "matches_won": participation["matches_won"]
        }
    }


@app.get("/api/user/{user_id}/events")
def poluchit_eventi_usera(user_id: int):
    """Получить события, в которых участвует пользователь"""
    # Активные события
    active_events = db.poluchit_aktivnie_eventi_usera(user_id)

    # Все события пользователя
    sql = """
        SELECT e.*, ep.score, ep.tasks_solved, ep.matches_won
        FROM events e
        JOIN event_participants ep ON e.id = ep.event_id
        WHERE ep.user_id = ?
        ORDER BY e.start_time DESC
    """
    all_events = db.vipolnit_zapros(sql, (user_id,), fetchall=True)

    # Парсим JSON
    if all_events:
        for e in all_events:
            if e.get("rules"):
                try:
                    e["rules"] = json.loads(e["rules"])
                except:
                    e["rules"] = {}
            if e.get("prizes"):
                try:
                    e["prizes"] = json.loads(e["prizes"])
                except:
                    e["prizes"] = {}

    return {
        "active_events": active_events,
        "all_events": all_events if all_events else []
    }


###################################
# API - МАРАФОНЫ
###################################

@app.get("/api/events/{event_id}/marathon/activity")
def poluchit_aktivnost_marafona(event_id: int, user_id: int = None, limit: int = 50):
    """Получить активность в марафоне"""
    event = db.poluchit_event_po_id(event_id)

    if event is None or event["type"] != "marathon":
        raise HTTPException(status_code=404, detail="Марафон не найден")

    activity = db.poluchit_aktivnost_marafona(event_id, user_id, limit)

    return {"activity": activity if activity else []}


###################################
# API - ТУРНИРЫ
###################################

@app.post("/api/events/{event_id}/tournament/start_round")
def nachat_raund_turnira(event_id: int, user_id: int):
    """Начать новый раунд турнира (только админ)"""
    user = db.poluchit_usera_po_id(user_id)
    if user is None or (user.get("isAdmin", False) == False and user.get("is_admin", 0) != 1):
        raise HTTPException(status_code=403, detail="Только для администраторов")

    event = db.poluchit_event_po_id(event_id)

    if event is None or event["type"] != "tournament":
        raise HTTPException(status_code=404, detail="Турнир не найден")

    if event["status"] != "active":
        raise HTTPException(status_code=400, detail="Турнир не активен")

    current_round = db.poluchit_tekushiy_raund_turnira(event_id)
    max_rounds = event["rules"].get("rounds", 5)

    if current_round > 0:
        # Проверяем завершение предыдущего раунда
        if not db.proverit_zavershenie_raunda(event_id, current_round):
            raise HTTPException(status_code=400, detail="Предыдущий раунд ещё не завершён")

    if current_round >= max_rounds:
        raise HTTPException(status_code=400, detail="Все раунды уже сыграны")

    new_round = current_round + 1

    # Получаем участников, сортируем по очкам (швейцарская система)
    participants = db.poluchit_uchastnikov_eventa(event_id, 1000)

    if len(participants) < 2:
        raise HTTPException(status_code=400, detail="Недостаточно участников")

    # Формируем пары
    pairs = []
    used = set()

    i = 0
    while i < len(participants):
        if participants[i]["user_id"] in used:
            i = i + 1
            continue

        # Ищем соперника
        j = i + 1
        while j < len(participants):
            if participants[j]["user_id"] not in used:
                # Нашли пару
                pairs.append({
                    "player1_id": participants[i]["user_id"],
                    "player1_name": participants[i].get("username", ""),
                    "player2_id": participants[j]["user_id"],
                    "player2_name": participants[j].get("username", "")
                })
                used.add(participants[i]["user_id"])
                used.add(participants[j]["user_id"])
                break
            j = j + 1

        i = i + 1

    # Создаём матчи турнира
    created_matches = []
    for pair in pairs:
        tm_id = db.sozdat_match_turnira(
            event_id,
            new_round,
            pair["player1_id"],
            pair["player2_id"]
        )
        created_matches.append({
            "tournament_match_id": tm_id,
            **pair
        })

    return {
        "success": True,
        "round": new_round,
        "matches": created_matches
    }


@app.get("/api/events/{event_id}/tournament/matches")
def poluchit_matchi_turnira(event_id: int, round_num: int = None):
    """Получить матчи турнира"""
    event = db.poluchit_event_po_id(event_id)

    if event is None or event["type"] != "tournament":
        raise HTTPException(status_code=404, detail="Турнир не найден")

    matches = db.poluchit_matchi_turnira(event_id, round_num)

    current_round = db.poluchit_tekushiy_raund_turnira(event_id)

    return {
        "matches": matches if matches else [],
        "current_round": current_round,
        "total_rounds": event["rules"].get("rounds", 5)
    }


@app.post("/api/events/{event_id}/tournament/start_match/{tournament_match_id}")
def nachat_match_turnira(event_id: int, tournament_match_id: int, user_id: int):
    """Начать конкретный матч турнира"""
    event = db.poluchit_event_po_id(event_id)

    if event is None or event["type"] != "tournament":
        raise HTTPException(status_code=404, detail="Турнир не найден")

    # Получаем матч турнира
    matches = db.poluchit_matchi_turnira(event_id)
    tm = None
    for m in matches:
        if m["id"] == tournament_match_id:
            tm = m
            break

    if tm is None:
        raise HTTPException(status_code=404, detail="Матч турнира не найден")

    if tm["status"] != "pending":
        raise HTTPException(status_code=400, detail="Матч уже начат или завершён")

    # Проверяем, что пользователь - участник матча
    if user_id != tm["player1_id"] and user_id != tm["player2_id"]:
        raise HTTPException(status_code=403, detail="Вы не участник этого матча")

    # Получаем задачи для матча
    subjects = event["rules"].get("subjects", ["math"])
    subject = subjects[0] if subjects else "math"

    all_tasks = db.poluchit_zadachi_s_filtrami(subject=subject)
    match_tasks = moy_shuffle(all_tasks)

    tasks_count = event["rules"].get("tasks_per_match", 5)
    selected_tasks = match_tasks[:tasks_count]

    # Создаём обычный матч
    player1 = db.poluchit_usera_po_id(tm["player1_id"])
    player2 = db.poluchit_usera_po_id(tm["player2_id"])

    match_id = db.sozdat_match(
        tm["player1_id"],
        player1.get("name") or player1.get("username"),
        player1.get("rating", 1000),
        tm["player2_id"],
        player2.get("name") or player2.get("username"),
        player2.get("rating", 1000),
        subject,
        "tournament",
        selected_tasks,
        False
    )

    # Обновляем матч турнира
    db.obnovit_match_turnira(tournament_match_id, match_id=match_id, status="active")

    # Обновляем event_id в матче
    db.obnovit_match(match_id, event_id=event_id, event_round=tm["round_num"])

    match = db.poluchit_match_po_id(match_id)

    return {"success": True, "match": match}

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
    return "<h1>EduBattle v3.2</h1><p>Положи index.html в папку с сервером</p>"


# запуск
if __name__ == "__main__":
    import uvicorn

    if db.proverit_bazu() == False:
        print("ОШИБКА: база данных не найдена!")
        print("Сначала запусти: python database.py")
        exit(1)

    print("=" * 50)
    print("EduBattle Server v3.2")
    print("+ Активный heartbeat каждые 10 сек")
    print("+ Мгновенная отмена при отключении")
    print("+ Рейтинги НЕ меняются при отмене")
    print("=" * 50)
    print("Открой http://localhost:8080")
    print("Админ: admin@edu.ru / admin123")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8080)