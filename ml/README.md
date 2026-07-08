# Offline ML pipeline — next-game points

Trains and ships the model that powers `GET /api/me/projection`. Feature logic is
imported from `courtside.ml` (the package in the Lambda image) so training and serving
never diverge. Heavy deps live in the `ml` uv group and never enter the serving image.

```
ml/
  config.py                 # env-driven pipeline config (region, feature group, S3, role, MLflow)
  feature_store/
    feature_group.py        # create/describe the SageMaker feature group (schema ← FEATURE_NAMES)
    ingest.py               # games → point-in-time feature records → PutRecord (online + offline)
    training_query.sql      # dedup-to-latest, leak-free training set from the offline store
  training/
    train.py                # Athena → XGBoost → MLflow → register Model Package (if it beats baseline)
  serving/
    inference.py            # SageMaker XGBoost script-mode handlers (CSV in → points out)
    deploy_endpoint.py      # latest Approved package → Serverless Inference endpoint
```

## One-time setup

The feature group, model package group, managed MLflow server, S3 bucket, and
SageMaker execution role are all provisioned by the `ml` module in the
**courtside-infra** repo. Pull the config from its Terraform outputs:

```bash
uv sync --group ml
export AWS_REGION=eu-central-1
export FEATURE_GROUP_NAME=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_feature_group_name)
export FEATURE_STORE_OFFLINE_S3=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_offline_store_s3)
export ATHENA_OUTPUT_S3=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_athena_output_s3)
export SAGEMAKER_ROLE_ARN=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_sagemaker_role_arn)
export MODEL_PACKAGE_GROUP=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_model_package_group)
export ENDPOINT_NAME=$(terraform -chdir=../courtside-infra/envs/prod output -raw ml_endpoint_name)
export MLFLOW_TRACKING_URI=$(terraform -chdir=../courtside-infra/envs/prod output -raw mlflow_tracking_server_arn)
```

> The feature group is Terraform-owned, so `ml.feature_store.feature_group` is
> describe/verify only in prod (`... feature_group describe`). Its schema mirrors
> `courtside.ml.features.FEATURE_NAMES`, which must stay in sync with the
> `ml_feature_names` list in `courtside-infra/envs/prod/main.tf`.

## Each run of the loop

```bash
# 1. ingest games into the local DB (scrape + seed), then:
uv run --group ml python -m ml.feature_store.ingest        # features → Feature Store
uv run --group ml python -m ml.training.train              # train, log to MLflow, register if it wins
# 2. approve the model package in the SageMaker console (or via CLI), then:
uv run --group ml python -m ml.serving.deploy_endpoint     # ship to the Serverless endpoint
```

Point the API at the endpoint by setting `SAGEMAKER_ENDPOINT_NAME` (and
`FEATURE_GROUP_NAME`) on the Lambda; until then the endpoint is unset and
`/api/me/projection` returns the trailing-average baseline.

## Cost

The Serverless endpoint scales to zero. The Feature Store online store and the managed
MLflow server are the small standing costs — delete the feature group and endpoint when
you're done experimenting.
