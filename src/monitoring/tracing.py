"""
OpenTelemetry distributed tracing setup with Jaeger exporter.
"""
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio

from src.config.settings import settings


def configure_tracing() -> None:
    """Configure OpenTelemetry tracing with Jaeger"""

    # Create resource
    resource = Resource.create(
        {
            "service.name": "cdc-pipeline",
            "service.version": "0.1.0",
            "deployment.environment": settings.environment,
        }
    )

    # Configure sampling: 100% errors, configurable % success
    sampler = ParentBasedTraceIdRatio(settings.observability.trace_sampling_rate)

    # Create tracer provider
    provider = TracerProvider(resource=resource, sampler=sampler)

    # Configure Jaeger exporter
    jaeger_exporter = JaegerExporter(
        agent_host_name=settings.observability.jaeger_agent_host,
        agent_port=settings.observability.jaeger_agent_port,
    )

    # Add span processor
    provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))

    # Set global tracer provider
    trace.set_tracer_provider(provider)


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer instance"""
    return trace.get_tracer(name)
