# -*- coding: utf-8 -*-
"""Сервис для работы с AI (DeepSeek через OpenRouter)"""

import aiohttp
import asyncio
import json
import re
from typing import AsyncGenerator, Optional, Dict, Any, List
from config import OPENROUTER_API_KEY, DEEPSEEK_MODEL, TASK_GENERATION_SYSTEM_PROMPT


class AIService:
    """Сервис для работы с DeepSeek R1 через OpenRouter"""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://edubattle.local",
            "X-Title": "EduBattle Task Generator"
        }
        self.conversation_history: Dict[str, List[Dict]] = {}

    def get_conversation(self, session_id: str) -> List[Dict]:
        """Получить историю диалога для сессии"""
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []
        return self.conversation_history[session_id]

    def add_message(self, session_id: str, role: str, content: str):
        """Добавить сообщение в историю"""
        conversation = self.get_conversation(session_id)
        conversation.append({"role": role, "content": content})

        # Ограничиваем историю последними 20 сообщениями
        if len(conversation) > 20:
            self.conversation_history[session_id] = conversation[-20:]

    def clear_conversation(self, session_id: str):
        """Очистить историю диалога"""
        self.conversation_history[session_id] = []

    async def stream_chat(
            self,
            session_id: str,
            user_message: str
    ) -> AsyncGenerator[str, None]:
        """
        Стриминг ответа от модели
        Yields: chunks текста
        """
        # Добавляем сообщение пользователя в историю
        self.add_message(session_id, "user", user_message)

        # Формируем запрос
        messages = [
                       {"role": "system", "content": TASK_GENERATION_SYSTEM_PROMPT}
                   ] + self.get_conversation(session_id)

        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 4096
        }

        full_response = ""

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        self.API_URL,
                        headers=self.headers,
                        json=payload
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        yield f"[ERROR] API Error: {response.status} - {error_text}"
                        return

                    # Читаем стрим
                    async for line in response.content:
                        line = line.decode('utf-8').strip()

                        if not line:
                            continue

                        if line.startswith("data: "):
                            data = line[6:]

                            if data == "[DONE]":
                                break

                            try:
                                chunk = json.loads(data)

                                if "choices" in chunk and len(chunk["choices"]) > 0:
                                    delta = chunk["choices"][0].get("delta", {})
                                    content = delta.get("content", "")

                                    if content:
                                        full_response += content
                                        yield content

                            except json.JSONDecodeError:
                                continue

        except aiohttp.ClientError as e:
            yield f"[ERROR] Connection error: {str(e)}"
            return
        except Exception as e:
            yield f"[ERROR] Unexpected error: {str(e)}"
            return

        # Сохраняем ответ ассистента в историю
        if full_response:
            self.add_message(session_id, "assistant", full_response)

    @staticmethod
    def parse_tasks_from_response(response_text: str) -> List[Dict[str, Any]]:
        """
        Парсинг задач из ответа модели
        Ищет JSON-блоки с задачами
        """
        tasks = []

        # Ищем все JSON блоки
        json_pattern = r'```json\s*([\s\S]*?)\s*```'
        matches = re.findall(json_pattern, response_text)

        for match in matches:
            try:
                data = json.loads(match)

                # Проверяем структуру задачи
                if "task" in data:
                    task = data["task"]
                elif all(key in data for key in ["subject", "question", "options", "answer"]):
                    task = data
                else:
                    continue

                # Валидация обязательных полей
                required_fields = ["subject", "question", "options", "answer"]
                if all(field in task for field in required_fields):
                    # Добавляем дефолтные значения
                    task.setdefault("difficulty", "medium")
                    task.setdefault("topic", "")
                    task.setdefault("hint", "")

                    # Убеждаемся, что options — это список
                    if isinstance(task["options"], list) and len(task["options"]) >= 2:
                        tasks.append(task)

            except json.JSONDecodeError:
                continue

        return tasks


# Глобальный экземпляр сервиса
ai_service = AIService()