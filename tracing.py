"""Langfuse Tracing - Agent 파이프라인 관측성 (v3 API)"""

import os
from langfuse import Langfuse
from langfuse.types import TraceContext
from dotenv import load_dotenv

load_dotenv()

langfuse = Langfuse(
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
    host=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
)


def create_pipeline_trace(issue_number):
    """파이프라인 trace_id 생성"""
    trace_id = langfuse.create_trace_id()
    ctx = TraceContext(trace_id=trace_id)
    langfuse.create_event(
        trace_context=ctx,
        name="pipeline_start",
        metadata={"issue_number": issue_number},
    )
    return trace_id


def _ctx(trace_id):
    return TraceContext(trace_id=trace_id)


def start_span(trace_id, name, input_data=None, metadata=None):
    return langfuse.start_span(
        trace_context=_ctx(trace_id),
        name=name,
        input=input_data,
        metadata=metadata or {},
    )


def start_generation(trace_id, name, model, input_data, metadata=None):
    return langfuse.start_generation(
        trace_context=_ctx(trace_id),
        name=name,
        model=model,
        input=input_data,
        metadata=metadata or {},
    )


def log_event(trace_id, name, input_data=None, output_data=None, metadata=None):
    langfuse.create_event(
        trace_context=_ctx(trace_id),
        name=name,
        input=input_data,
        output=output_data,
        metadata=metadata or {},
    )


def score_trace(trace_id, name, value, comment=""):
    langfuse.create_score(
        trace_id=trace_id,
        name=name,
        value=value,
        comment=comment,
    )


def flush():
    langfuse.flush()
