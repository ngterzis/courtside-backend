-- Point-in-time-correct training set from the Feature Store offline store.
--
-- The offline store is append-only, so a record_id can appear multiple times; we keep
-- only the most recent write per record_id. Current-form serving rows (label = -1) and
-- Feature Store's soft-deleted rows are excluded. Each row's features were already built
-- strictly from games before its event date (see courtside.ml.features), so selecting
-- them here introduces no leakage.
--
-- {table} is substituted with the offline store's Glue table name at runtime.
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY record_id
            ORDER BY write_time DESC
        ) AS rn
    FROM "{table}"
    WHERE NOT is_deleted
)
SELECT *
FROM ranked
WHERE rn = 1
  AND label >= 0
ORDER BY event_time;
