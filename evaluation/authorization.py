"""Explicit bounded real-simulator scope; never authorizes real-world shopping.

This object records an already-approved invocation, not an approval mechanism or
security sandbox. The interactive entrypoint requires the operator to opt in.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class RealRunScope:
    task_ids: tuple[int, ...]
    model: str = 'gpt-6.1-sol'
    host: str = 'st.walkcoding.top'
    monetary_cap_usd: None = None
    max_steps: int = 30
    max_model_calls: int = 30

    def __post_init__(self):
        if len(self.task_ids) != 20 or len(set(self.task_ids)) != 20:
            raise ValueError('real scope requires exactly 20 distinct development IDs')
        if any(type(i) is not int or i < 0 for i in self.task_ids):
            raise ValueError('invalid development ID')
        if self.model != 'gpt-6.1-sol' or self.host != 'st.walkcoding.top':
            raise ValueError('scope outside approved exact relay/model')
        if self.max_steps != 30 or self.max_model_calls != 30 or self.monetary_cap_usd is not None:
            raise ValueError('scope differs from fixed 30-step/30-call no-monetary-cap plan')
