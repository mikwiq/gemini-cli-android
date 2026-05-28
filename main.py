import os
import subprocess
import threading
import flet as ft
from google import genai
from google.genai import types

# ==========================================
# ЧАСТЬ 1: СУПЕР-ПРОМПТ И СИСТЕМНАЯ ЛОГИКА АГЕНТА
# ==========================================

# Тяжеловесный системный промпт в стиле Claude Code / Gemini CLI
CLI_AGENT_PROMPT = (
    "You are an elite, fully autonomous CLI Agent and System Engineer operating inside an Android app sandbox terminal.\n\n"
    "YOUR CORE PROTOCOL:\n"
    "1. Objective: Solve the user's task completely using local shell commands via the `execute_command` tool.\n"
    "2. ReAct Framework: For every turn, you must follow the Reason-Act-Observe pattern. Think before acting.\n"
    "3. Self-Correction: If a command fails (returns stderr or non-zero exit code), do not give up and do not ask the user for help immediately. "
    "Analyze the error, fix your syntax, find alternative commands, or write helper scripts to bypass the limitation.\n"
    "4. Verification: After creating a file or running a script, execute a command to verify it actually works and outputs the expected result.\n"
    "5. Environment awareness: You are running inside an Android app storage sandbox. You have access to basic Linux/Android commands and Python 3. "
    "If a specialized CLI tool is missing, use Python built-ins or lightweight shell scripts to achieve the same goal.\n\n"
    "CRITICAL OUTPUT STYLE:\n"
    "- Be concise in your direct text responses. Let your terminal actions do the talking.\n"
    "- Do not output large blocks of code directly to the user if your task is to deploy or create them; instead, use your tools to write them directly into files."
)

class GeminiAndroidAgent:
    def __init__(self, api_key: str, log_view_callback):
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash"  # Оптимальна для быстрого вызова инструментов
        self.log_callback = log_view_callback
        
        # Настройка чат-сессии с инструментами
        self.chat = self.client.chats.create(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=CLI_AGENT_PROMPT,
                tools=[self.execute_command],
                temperature=0.1,  # Минимальный хаос, максимальная точность
            )
        )

    def execute_command(self, command: str) -> str:
        """Инструмент, который агент вызывает самостоятельно для работы в консоли."""
        self.log_callback(f"❯ {command}", is_cmd=True)
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=20
            )
            output = []
            if result.stdout:
                output.append(result.stdout)
            if result.stderr:
                output.append(f"[STDERR]\n{result.stderr}")
            
            res_str = "\n".join(output) if output else "Executed (No output)"
            return res_str
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 20 seconds."
        except Exception as e:
            return f"Error executing command: {str(e)}"

    def send(self, prompt: str) -> str:
        # Отправляем запрос, SDK сам закрутит цикл Function Calling, если модель вызовет инструмент
        response = self.chat.send_message(prompt)
        return response.text

# ==========================================
# ЧАСТЬ 2: ИНТЕРФЕЙС ПРИЛОЖЕНИЯ (FLET UI)
# ==========================================

def main(page: ft.Page):
    page.title = "Gemini CLI Agent Mobile"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 15
    
    agent = None

    # Элементы авторизации
    api_key_input = ft.TextField(
        label="Вставь свой Gemini API Ключ", 
        password=True, 
        can_reveal_password=True,
        expand=True
    )
    
    # Окно логов терминала (в стиле оригинального CLI)
    terminal_logs = ft.Column(scroll=ft.ScrollMode.ALWAYS, expand=True)
    
    terminal_container = ft.Container(
        content=terminal_logs,
        border=ft.border.all(1, ft.Colors.GREEN_400),
        border_radius=8,
        bgcolor=ft.Colors.BLACK,
        padding=10,
        expand=True,
    )

    def append_log(text, is_cmd=False, is_agent=False):
        """Безопасное добавление строк в терминал из любых потоков."""
        if is_cmd:
            color = ft.Colors.GREEN_ACCENT
        elif is_agent:
            color = ft.Colors.LIGHT_BLUE_200
        else:
            color = ft.Colors.WHITE
            
        terminal_logs.controls.append(
            ft.Text(text, font_family="monospace", color=color, size=13)
        )
        page.update()

    def start_agent(e):
        nonlocal agent
        if not api_key_input.value:
            api_key_input.error_text = "Ключ обязателен!"
            page.update()
            return
        
        try:
            agent = GeminiAndroidAgent(api_key_input.value, log_view_callback=append_log)
            auth_row.visible = False
            chat_row.visible = True
            append_log("[SYS] Агент успешно инициализирован. Промпт Claude Code активен.")
            page.update()
        except Exception as ex:
            api_key_input.error_text = f"Ошибка: {str(ex)}"
            page.update()

    auth_row = ft.Row([
        api_key_input,
        ft.ElevatedButton("Запустить", on_click=start_agent, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE)
    ])

    # Элементы ввода для пользователя
    user_input = ft.TextField(hint_text="Поручи задачу агенту...", expand=True, on_submit=lambda e: send_message_thread(e))
    
    def process_agent_work(prompt):
        try:
            # Запуск логики агента
            final_response = agent.send(prompt)
            append_log(f"\n[AGNT Ответ]: {final_response}", is_agent=True)
        except Exception as e:
            append_log(f"\n[SYS КРИТИЧЕСКАЯ ОШИБКА]: {str(e)}", is_cmd=False)
        finally:
            user_input.disabled = False
            progress_bar.visible = False
            page.update()

    def send_message_thread(e):
        if not user_input.value or not agent:
            return
        
        prompt = user_input.value
        user_input.value = ""
        user_input.disabled = True
        progress_bar.visible = True
        
        append_log(f"\n[USER]: {prompt}")
        page.update()
        
        # Запускаем в отдельном потоке, чтобы UI не намертво замерзал во время размышлений модели
        threading.Thread(target=process_agent_work, args=(prompt,), daemon=True).start()

    progress_bar = ft.ProgressBar(visible=False, color=ft.Colors.GREEN_400)
    
    chat_row = ft.Row([
        user_input,
        ft.IconButton(icon=ft.Icons.SEND, on_click=send_message_thread, icon_color=ft.Colors.GREEN_400)
    ], visible=False)

    # Добавляем компоненты на экран
    page.add(
        ft.Text("Gemini CLI Agent Sandbox", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
        auth_row,
        terminal_container,
        progress_bar,
        chat_row
    )

if __name__ == "__main__":
    ft.app(target=main)
