"""Main PhoneAgent class for orchestrating phone automation."""

import json
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from phone_agent.actions import ActionHandler
from phone_agent.actions.handler import do, finish, parse_action
from phone_agent.adb import get_current_app, get_screenshot
from phone_agent.config import get_messages, get_system_prompt
from phone_agent.model import ModelClient, ModelConfig
from phone_agent.model.client import MessageBuilder


@dataclass
class AgentConfig:
    """Configuration for the PhoneAgent."""

    max_steps: int = 100
    device_id: str | None = None
    lang: str = "cn"
    system_prompt: str | None = None
    verbose: bool = True
    max_context_messages: int = 20  # Maximum messages in context (excluding system)

    def __post_init__(self):
        if self.system_prompt is None:
            self.system_prompt = get_system_prompt(self.lang)


@dataclass
class StepResult:
    """Result of a single agent step."""

    success: bool
    finished: bool
    action: dict[str, Any] | None
    thinking: str
    message: str | None = None


class PhoneAgent:
    """
    AI-powered agent for automating Android phone interactions.

    The agent uses a vision-language model to understand screen content
    and decide on actions to complete user tasks.

    Args:
        model_config: Configuration for the AI model.
        agent_config: Configuration for the agent behavior.
        confirmation_callback: Optional callback for sensitive action confirmation.
        takeover_callback: Optional callback for takeover requests.

    Example:
        >>> from phone_agent import PhoneAgent
        >>> from phone_agent.model import ModelConfig
        >>>
        >>> model_config = ModelConfig(base_url="http://localhost:8000/v1")
        >>> agent = PhoneAgent(model_config)
        >>> agent.run("Open WeChat and send a message to John")
    """

    def __init__(
        self,
        model_config: ModelConfig | None = None,
        agent_config: AgentConfig | None = None,
        confirmation_callback: Callable[[str], bool] | None = None,
        takeover_callback: Callable[[str], None] | None = None,
    ):
        self.model_config = model_config or ModelConfig()
        self.agent_config = agent_config or AgentConfig()

        self.model_client = ModelClient(self.model_config)
        self.action_handler = ActionHandler(
            device_id=self.agent_config.device_id,
            confirmation_callback=confirmation_callback,
            takeover_callback=takeover_callback,
        )

        self._context: list[dict[str, Any]] = []
        self._step_count = 0

    def run(self, task: str) -> str:
        """
        Run the agent to complete a task.

        Args:
            task: Natural language description of the task.

        Returns:
            Final message from the agent.
        """
        self._context = []
        self._step_count = 0

        # First step with user prompt
        result = self._execute_step(task, is_first=True)

        if result.finished:
            return result.message or "Task completed"

        # Continue until finished or max steps reached
        while (
            self._step_count < self.agent_config.max_steps
            or self.agent_config.max_steps <= 0
        ):
            result = self._execute_step(is_first=False)

            if result.finished:
                return result.message or "Task completed"

        return "Max steps reached"

    def step(self, task: str | None = None) -> StepResult:
        """
        Execute a single step of the agent.

        Useful for manual control or debugging.

        Args:
            task: Task description (only needed for first step).

        Returns:
            StepResult with step details.
        """
        is_first = len(self._context) == 0

        if is_first and not task:
            raise ValueError("Task is required for the first step")

        return self._execute_step(task, is_first)

    def reset(self) -> None:
        """Reset the agent state for a new task."""
        self._context = []
        self._step_count = 0

    def _trim_context(self) -> None:
        """Trim context to keep only recent messages within token limit."""
        # If already within budget (max_context_messages + system), keep as-is
        if len(self._context) <= self.agent_config.max_context_messages + 1:
            return

        # Anchor messages that must stay at the front:
        # 1) system prompt
        # 2) initial user task
        # 3) first assistant reply (model's initial understanding)
        system_msg = next(
            (m for m in self._context if m.get("role") == "system"), self._context[0]
        )
        initial_task_msg = next(
            (m for m in self._context if m.get("role") == "user"), None
        )
        first_assistant_msg = next(
            (m for m in self._context if m.get("role") == "assistant"), None
        )

        # Preserve anchor order based on their first appearance
        anchors: list[dict[str, Any]] = []
        for anchor in (system_msg, initial_task_msg, first_assistant_msg):
            if anchor and anchor not in anchors:
                anchors.append(anchor)

        # Remaining messages (excluding anchors)
        remaining = [m for m in self._context if m not in anchors]

        # Budget excludes the system message
        available_slots = max(
            self.agent_config.max_context_messages - (len(anchors) - 1), 0
        )
        recent_msgs = remaining[-available_slots:] if available_slots > 0 else []

        # Rebuild context: system first, then other anchors, then recent messages
        new_context: list[dict[str, Any]] = []
        if system_msg:
            new_context.append(system_msg)
        for anchor in anchors:
            if anchor is system_msg:
                continue
            if anchor not in recent_msgs:
                new_context.append(anchor)
        new_context.extend(recent_msgs)

        self._context = new_context

    def _retry_action_request(self, failed_action_text: str) -> dict[str, Any]:
        """Retry once with a stricter format reminder when action parsing fails."""
        retry_prompt = (
            "上一次回复未按格式返回。请仅返回一个动作调用，严格使用以下格式之一：\n"
            '1) do(action="...", ...)，继续执行任务时使用\n'
            '2) finish(message="...")，任务完成时使用\n'
            "不要添加任何其他文本或解释，不要输出自然语言描述。"
        )

        # Add retry reminder as the latest user message (no image) and trim context
        self._context.append(MessageBuilder.create_user_message(text=retry_prompt))
        self._trim_context()

        retry_response = None
        try:
            retry_response = self.model_client.request(self._context)
            return parse_action(retry_response.action)
        except Exception:
            if self.agent_config.verbose:
                traceback.print_exc()
            fallback_text = (
                retry_response.action
                if retry_response is not None
                else failed_action_text
            )
            return finish(message=fallback_text)

    def _execute_step(
        self, user_prompt: str | None = None, is_first: bool = False
    ) -> StepResult:
        """Execute a single step of the agent loop."""
        self._step_count += 1

        # Capture current screen state
        screenshot = get_screenshot(self.agent_config.device_id)
        current_app = get_current_app(self.agent_config.device_id)

        # Build messages
        if is_first:
            self._context.append(
                MessageBuilder.create_system_message(self.agent_config.system_prompt)
            )

            screen_info = MessageBuilder.build_screen_info(current_app)
            text_content = f"{user_prompt}\n\n{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )
        else:
            screen_info = MessageBuilder.build_screen_info(current_app)
            text_content = f"** Screen Info **\n\n{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )

        # Get model response
        try:
            # Trim context to prevent token limit issues
            self._trim_context()

            msgs = get_messages(self.agent_config.lang)
            print("\n" + "=" * 50)
            print(f"💭 {msgs['thinking']}:")
            print("-" * 50)
            response = self.model_client.request(self._context)
        except Exception as e:
            if self.agent_config.verbose:
                traceback.print_exc()
            return StepResult(
                success=False,
                finished=True,
                action=None,
                thinking="",
                message=f"Model error: {e}",
            )

        # Parse action from response
        try:
            action = parse_action(response.action)
        except ValueError:
            if self.agent_config.verbose:
                traceback.print_exc()
            action = self._retry_action_request(response.action)

        if self.agent_config.verbose:
            # Print thinking process
            print("-" * 50)
            print(f"🎯 {msgs['action']}:")
            print(json.dumps(action, ensure_ascii=False, indent=2))
            print("=" * 50 + "\n")

        # Remove image from context to save space
        self._context[-1] = MessageBuilder.remove_images_from_message(self._context[-1])

        # Execute action
        try:
            result = self.action_handler.execute(
                action, screenshot.width, screenshot.height
            )
        except Exception as e:
            if self.agent_config.verbose:
                traceback.print_exc()
            result = self.action_handler.execute(
                finish(message=str(e)), screenshot.width, screenshot.height
            )

        # Add assistant response to context
        self._context.append(
            MessageBuilder.create_assistant_message(
                f"<think>{response.thinking}</think><answer>{response.action}</answer>"
            )
        )

        # Check if finished
        finished = action.get("_metadata") == "finish" or result.should_finish

        if finished and self.agent_config.verbose:
            msgs = get_messages(self.agent_config.lang)
            print("\n" + "🎉 " + "=" * 48)
            print(
                f"✅ {msgs['task_completed']}: {result.message or action.get('message', msgs['done'])}"
            )
            print("=" * 50 + "\n")

        return StepResult(
            success=result.success,
            finished=finished,
            action=action,
            thinking=response.thinking,
            message=result.message or action.get("message"),
        )

    @property
    def context(self) -> list[dict[str, Any]]:
        """Get the current conversation context."""
        return self._context.copy()

    @property
    def step_count(self) -> int:
        """Get the current step count."""
        return self._step_count
