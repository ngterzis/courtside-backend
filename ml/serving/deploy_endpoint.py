"""Deploy the latest Approved model package to a Serverless Inference endpoint.

Serverless is chosen deliberately: it scales to zero and bills per invocation, so the
endpoint costs nothing while idle — the same Model -> EndpointConfig -> Endpoint workflow
as a provisioned real-time endpoint, without the 24/7 instance bill. Swap
`ServerlessInferenceConfig` for `instance_type=...` to learn the provisioned path (and
remember to delete the endpoint afterwards).

    uv run --group ml python -m ml.serving.deploy_endpoint
"""

from __future__ import annotations

import boto3
import sagemaker
from sagemaker import ModelPackage
from sagemaker.serverless import ServerlessInferenceConfig

from ml.config import PipelineConfig


def _latest_approved_package_arn(sm_client, group: str) -> str:
    resp = sm_client.list_model_packages(
        ModelPackageGroupName=group,
        ModelApprovalStatus="Approved",
        SortBy="CreationTime",
        SortOrder="Descending",
        MaxResults=1,
    )
    packages = resp.get("ModelPackageSummaryList", [])
    if not packages:
        raise RuntimeError(f"no Approved model package in group {group}")
    return packages[0]["ModelPackageArn"]


def deploy(cfg: PipelineConfig) -> None:
    boto_session = boto3.Session(region_name=cfg.region)
    session = sagemaker.Session(boto_session)
    sm_client = boto_session.client("sagemaker")

    package_arn = _latest_approved_package_arn(sm_client, cfg.model_package_group)
    model = ModelPackage(
        role=cfg.role_arn,
        model_package_arn=package_arn,
        sagemaker_session=session,
    )

    serverless = ServerlessInferenceConfig(memory_size_in_mb=2048, max_concurrency=5)
    exists = any(
        e["EndpointName"] == cfg.endpoint_name
        for e in sm_client.list_endpoints(NameContains=cfg.endpoint_name)["Endpoints"]
    )

    model.deploy(
        serverless_inference_config=serverless,
        endpoint_name=cfg.endpoint_name,
        update_endpoint=exists,
    )
    print(f"{'updated' if exists else 'created'} endpoint {cfg.endpoint_name} "
          f"from {package_arn}")


if __name__ == "__main__":
    deploy(PipelineConfig.from_env())
