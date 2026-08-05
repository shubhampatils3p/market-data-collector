CREATE TABLE IF NOT EXISTS option_market_data (

    id BIGSERIAL PRIMARY KEY,

    "Index_Name" VARCHAR(20) NOT NULL,
    "Timestamp" TIMESTAMP NOT NULL,

    "Index_Open" DOUBLE PRECISION NOT NULL,
    "Index_High" DOUBLE PRECISION NOT NULL,
    "Index_Low" DOUBLE PRECISION NOT NULL,
    "Index_Close" DOUBLE PRECISION NOT NULL,

    "Target_Strike" INTEGER NOT NULL,

    "CE_Symbol" VARCHAR(40) NOT NULL,

    "CE_Open" DOUBLE PRECISION NOT NULL,
    "CE_High" DOUBLE PRECISION NOT NULL,
    "CE_Low" DOUBLE PRECISION NOT NULL,
    "CE_Close" DOUBLE PRECISION NOT NULL,

    "CE_Volume_Delta" BIGINT NOT NULL,
    "CE_Cumulative_Vol" BIGINT NOT NULL,
    "CE_Open_Interest" BIGINT NOT NULL,
    "CE_OI_Change" BIGINT NOT NULL,

    "CE_Delta" DOUBLE PRECISION,
    "CE_Gamma" DOUBLE PRECISION,
    "CE_Theta" DOUBLE PRECISION,
    "CE_Vega" DOUBLE PRECISION,

    "PE_Symbol" VARCHAR(40) NOT NULL,

    "PE_Open" DOUBLE PRECISION NOT NULL,
    "PE_High" DOUBLE PRECISION NOT NULL,
    "PE_Low" DOUBLE PRECISION NOT NULL,
    "PE_Close" DOUBLE PRECISION NOT NULL,

    "PE_Volume_Delta" BIGINT NOT NULL,
    "PE_Cumulative_Vol" BIGINT NOT NULL,
    "PE_Open_Interest" BIGINT NOT NULL,
    "PE_OI_Change" BIGINT NOT NULL,

    "PE_Delta" DOUBLE PRECISION,
    "PE_Gamma" DOUBLE PRECISION,
    "PE_Theta" DOUBLE PRECISION,
    "PE_Vega" DOUBLE PRECISION,

    "ATM_Distance" DOUBLE PRECISION NOT NULL,

    "IV_CE" DOUBLE PRECISION,
    "IV_PE" DOUBLE PRECISION,

    "PCR_Strike" DOUBLE PRECISION NOT NULL,

    "VIX_Snapshot" DOUBLE PRECISION,

    "Row_Hash" CHAR(32) NOT NULL,

    "CE_Price_Source" VARCHAR(20) NOT NULL,
    "PE_Price_Source" VARCHAR(20) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_option_row_hash
ON option_market_data("Row_Hash");

CREATE INDEX idx_option_timestamp
ON option_market_data("Timestamp");

CREATE INDEX idx_option_strike
ON option_market_data("Target_Strike");

CREATE INDEX idx_option_ce_symbol
ON option_market_data("CE_Symbol");

CREATE INDEX idx_option_pe_symbol
ON option_market_data("PE_Symbol");