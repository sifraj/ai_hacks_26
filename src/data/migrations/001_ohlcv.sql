CREATE TABLE IF NOT EXISTS ohlcv (
    time   TIMESTAMPTZ NOT NULL,
    asset  TEXT NOT NULL,
    interval TEXT NOT NULL,
    open   FLOAT8 NOT NULL,
    high   FLOAT8 NOT NULL,
    low    FLOAT8 NOT NULL,
    close  FLOAT8 NOT NULL,
    volume FLOAT8 NOT NULL
);

SELECT create_hypertable('ohlcv', 'time', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS ohlcv_asset_interval_time_idx
    ON ohlcv (asset, interval, time DESC);
