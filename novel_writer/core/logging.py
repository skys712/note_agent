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
    debug=True 时输出额外的诊断信息（prompt 大小、响应预览等）。
    """

    def __init__(self, verbose: bool = True, debug: bool = False):
        self.verbose = verbose
        self.debug_mode = debug
        self.stats = SessionStats()
        self._local = threading.local()
        self._lock = threading.Lock()
        self._t0 = time.time()

    # ---- 基础输出 ----

    def _print(self, *args, **kwargs) -> None:
        """统一 print，强制 flush 确保 Windows 终端实时显示"""
        print(*args, flush=True, **kwargs)

    def _ts(self) -> str:
        """返回距会话开始的时间戳字符串 [MM:SS]"""
        elapsed = time.time() - self._t0
        m, s = divmod(int(elapsed), 60)
        return f"[{m:02d}:{s:02d}]"

    # ---- 阶段标记 ----

    def phase(self, title: str) -> None:
        """打印阶段标题"""
        if not self.verbose:
            return
        self._print(f"\n{'=' * 60}")
        self._print(f"  {title}")
        self._print(f"{'=' * 60}")

    def section(self, title: str) -> None:
        """打印子阶段标题"""
        if not self.verbose:
            return
        self._print(f"\n{'-' * 60}")
        self._print(f"  {title}")
        self._print(f"{'-' * 60}")

    # ---- 步骤追踪 ----

    def step_start(self, step: int, total: int, agent_name: str, action: str,
                   input_size: int = 0, context_size: int = 0) -> None:
        """Agent 步骤开始"""
        if not self.verbose:
            return
        self._local.section_start = time.time()
        label = f"[{step}/{total}] {agent_name}"
        ts = self._ts()
        self._print(f"\n  {ts} {label} - {action} ", end="")
        if self.debug_mode and (input_size or context_size):
            sizes = []
            if input_size:
                sizes.append(f"input={input_size:,}ch")
            if context_size:
                sizes.append(f"ctx={context_size:,}ch")
            self._print(f" ({', '.join(sizes)})", end="")
        self._print("", end="")

    def step_end(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        result_chars: int = 0,
        success: bool = True,
        error: str = "",
        response_preview: str = "",
        max_tokens: int = 0,
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
        self._print(f" {status}")
        detail = f"    in: {input_tokens:,} tk  out: {output_tokens:,} tk"
        if output_tokens > 0 and input_tokens > 0:
            detail += f"  ({output_tokens / input_tokens:.1%} 输出比)"
        if max_tokens > 0 and output_tokens > 0:
            detail += f"  [{output_tokens / max_tokens:.0%} 预算]"
        detail += f"  time: {elapsed:,.0f}ms"
        if result_chars > 0:
            detail += f"  chars: {result_chars:,}"
        self._print(detail)
        if self.debug_mode and response_preview:
            preview = response_preview[:120].replace("\n", "\\n")
            self._print(f"    preview: {preview}...")
        if error:
            self._print(f"    error: {error}")

    def debug(self, msg: str) -> None:
        """输出 debug 信息（仅 debug 模式）"""
        if self.debug_mode and self.verbose:
            self._print(f"  {self._ts()} [DEBUG] {msg}")

    # ---- 流式进度 ----

    def stream_progress(self, total_chars: int) -> None:
        """流式传输进度回调，由 LLMClient 在接收 chunk 时调用"""
        if not self.verbose:
            return
        started = getattr(self._local, "stream_started", False)
        if not started:
            stream_start = time.time()
            self._local.stream_start_time = stream_start
            self._print("  [streaming] ", end="")
            self._local.stream_started = True
        milestone = getattr(self._local, "progress_milestone", 0)
        # 每接收 150 字符显示一个点
        if total_chars - milestone >= 150:
            self._local.progress_milestone = total_chars
            if total_chars >= 1000 and total_chars % 1000 < 150:
                # 每 1000 字符显示计数
                self._print(f"{total_chars // 1000}k", end="")
            else:
                self._print(".", end="")

    def stream_end(self, total_chars: int) -> None:
        """流式传输结束，清理进度状态"""
        if not self.verbose:
            return
        started = getattr(self._local, "stream_started", False)
        if started:
            t0 = getattr(self._local, "stream_start_time", time.time())
            elapsed = time.time() - t0
            self._print(f" {total_chars:,} chars ({elapsed:.1f}s)", end="")
        self._local.progress_milestone = 0
        self._local.stream_started = False

    # ---- 跳过 / 记录 ----

    def step_skip(self, reason: str = "") -> None:
        """标记步骤跳过"""
        if not self.verbose:
            return
        msg = "  [SKIP] 跳过"
        if reason:
            msg += f" ({reason})"
        self._print(msg)

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

    # ---- 摘要 ----

    def summary(self) -> None:
        """打印整个会话的统计摘要"""
        s = self.stats
        if s.total_calls == 0:
            return
        self._print(f"\n{'=' * 60}")
        self._print("  会话统计")
        self._print(f"{'=' * 60}")
        self._print(f"  总调用次数:    {s.total_calls}")
        self._print(f"  总输入 Token:  {s.total_input_tokens:,}")
        self._print(f"  总输出 Token:  {s.total_output_tokens:,}")
        self._print(f"  Token 合计:    {s.total_input_tokens + s.total_output_tokens:,}")
        total_s = s.total_duration_ms / 1000
        self._print(f"  总耗时:        {total_s:,.1f}s")
        if s.total_calls > 1:
            self._print(f"  平均耗时:      {s.total_duration_ms / s.total_calls:,.0f}ms/次")
        if total_s > 0:
            tok_per_s = (s.total_output_tokens) / total_s
            self._print(f"  输出速率:      {tok_per_s:,.0f} tk/s")
        self._print()

    def detail_report(self) -> None:
        """打印每次调用的详细报告"""
        s = self.stats
        if not s.records:
            return
        self._print(f"\n{'-' * 60}")
        self._print("  调用明细")
        self._print(f"{'-' * 60}")
        header = f"  {'Agent':<16s} {'Action':<12s} {'输入':>8s} {'输出':>8s} {'耗时':>8s} {'结果':>8s}"
        self._print(header)
        self._print(f"  {'-' * 68}")
        for r in s.records:
            status = "[OK]" if r.success else "[FAIL]"
            self._print(
                f"  {r.agent_name:<16s} {r.action:<12s} "
                f"{r.input_tokens:>6,}tk {r.output_tokens:>6,}tk "
                f"{r.duration_ms:>6,.0f}ms {r.result_chars:>6,}字 {status}"
            )
        self._print()
