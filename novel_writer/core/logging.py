"""执行日志系统：追踪 Agent 调用、Token 消耗、耗时等细节"""

import threading
import time
from dataclasses import dataclass, field


@dataclass
class CallRecord:
    """单次 LLM 调用记录"""
    agent_name: str
    action: str
    input_tokens: int
    output_tokens: int
    duration_ms: float
    result_chars: int
    success: bool
    error: str = ""


@dataclass
class SessionStats:
    """会话统计"""
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_duration_ms: float = 0.0
    records: list[CallRecord] = field(default_factory=list)


class ExecutionLogger:
    """执行日志记录器

    负责格式化输出 Agent 调用详情，追踪 Token 消耗统计。
    """

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.stats = SessionStats()
        self._local = threading.local()
        self._lock = threading.Lock()

    def phase(self, title: str) -> None:
        """打印阶段标题"""
        if not self.verbose:
            return
        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")

    def section(self, title: str) -> None:
        """打印子阶段标题"""
        if not self.verbose:
            return
        print(f"\n{'-' * 60}")
        print(f"  {title}")
        print(f"{'-' * 60}")

    def step_start(self, step: int, total: int, agent_name: str, action: str) -> None:
        """Agent 步骤开始"""
        if not self.verbose:
            return
        self._local.section_start = time.time()
        label = f"[{step}/{total}] {agent_name}"
        print(f"\n  {label} - {action} ", end="", flush=True)

    def step_end(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        result_chars: int = 0,
        success: bool = True,
        error: str = "",
    ) -> None:
        """Agent 步骤结束，输出本步骤统计"""
        if not self.verbose:
            return
        start = getattr(self._local, "section_start", time.time())
        elapsed = (time.time() - start) * 1000
        with self._lock:
            self.stats.total_calls += 1
            self.stats.total_input_tokens += input_tokens
            self.stats.total_output_tokens += output_tokens
            self.stats.total_duration_ms += elapsed

        status = "[OK]" if success else "[FAIL]"
        print(f" {status}")
        detail = f"    in: {input_tokens:,} tk  out: {output_tokens:,} tk"
        if output_tokens > 0:
            detail += f"  ({output_tokens / max(input_tokens, 1):.1%} 输出比)"
        detail += f"  time: {elapsed:,.0f}ms"
        if result_chars > 0:
            detail += f"  chars: {result_chars:,}"
        print(detail)

    def stream_progress(self, total_chars: int) -> None:
        """流式传输进度回调，由 LLMClient 在接收 chunk 时调用"""
        if not self.verbose:
            return
        started = getattr(self._local, "stream_started", False)
        if not started:
            print("  [streaming] ", end="", flush=True)
            self._local.stream_started = True
        milestone = getattr(self._local, "progress_milestone", 0)
        # 每接收 300 字符显示一个点
        if total_chars - milestone >= 300:
            self._local.progress_milestone = total_chars
            print(".", end="", flush=True)

    def stream_end(self, total_chars: int) -> None:
        """流式传输结束，清理进度状态"""
        if not self.verbose:
            return
        started = getattr(self._local, "stream_started", False)
        if started:
            print(f" {total_chars:,} chars", end="", flush=True)
        self._local.progress_milestone = 0
        self._local.stream_started = False

    def step_skip(self, reason: str = "") -> None:
        """标记步骤跳过"""
        if not self.verbose:
            return
        msg = "  [SKIP] 跳过"
        if reason:
            msg += f" ({reason})"
        print(msg)

    def record_call(
        self,
        agent_name: str,
        action: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
        result_chars: int,
        success: bool = True,
        error: str = "",
    ) -> None:
        """记录一次 LLM 调用到统计"""
        with self._lock:
            self.stats.records.append(CallRecord(
                agent_name=agent_name,
                action=action,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                result_chars=result_chars,
                success=success,
                error=error,
            ))

    def summary(self) -> None:
        """打印整个会话的统计摘要"""
        s = self.stats
        if s.total_calls == 0:
            return
        print(f"\n{'=' * 60}")
        print(f"  会话统计")
        print(f"{'=' * 60}")
        print(f"  总调用次数:    {s.total_calls}")
        print(f"  总输入 Token:  {s.total_input_tokens:,}")
        print(f"  总输出 Token:  {s.total_output_tokens:,}")
        print(f"  Token 合计:    {s.total_input_tokens + s.total_output_tokens:,}")
        print(f"  总耗时:        {s.total_duration_ms/1000:,.1f}s")
        if s.total_calls > 1:
            print(f"  平均耗时:      {s.total_duration_ms/s.total_calls:,.0f}ms/次")
        print()

    def detail_report(self) -> None:
        """打印每次调用的详细报告"""
        s = self.stats
        if not s.records:
            return
        print(f"\n{'-' * 60}")
        print(f"  调用明细")
        print(f"{'-' * 60}")
        header = f"  {'Agent':<16s} {'Action':<12s} {'输入':>8s} {'输出':>8s} {'耗时':>8s} {'结果':>8s}"
        print(header)
        print(f"  {'-' * 68}")
        for r in s.records:
            status = "[OK]" if r.success else "[FAIL]"
            print(
                f"  {r.agent_name:<16s} {r.action:<12s} "
                f"{r.input_tokens:>6,}tk {r.output_tokens:>6,}tk "
                f"{r.duration_ms:>6,.0f}ms {r.result_chars:>6,}字 {status}"
            )
        print()
