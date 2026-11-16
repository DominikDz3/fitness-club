import os

from py_eureka_client.eureka_client import EurekaClient


def create_eureka_client(service_name: str, default_port: int) -> EurekaClient:
    return EurekaClient(
        eureka_server=os.getenv("EUREKA_SERVER_URL", "http://127.0.0.1:8761"),
        eureka_context="/eureka",
        app_name=os.getenv("SERVICE_NAME", service_name),
        instance_ip=os.getenv("INSTANCE_IP", "127.0.0.1"),
        instance_host=os.getenv("INSTANCE_HOST", "localhost"),
        instance_port=int(os.getenv("SERVICE_PORT", str(default_port))),
        strict_service_error_policy=False,
    )