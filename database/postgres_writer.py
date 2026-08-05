from psycopg2.extras import execute_values

from database.db import get_connection, release_connection


INSERT_QUERY = """
INSERT INTO option_market_data (
    
"Index_Name",

"Timestamp",

"Index_Open",
"Index_High",
"Index_Low",
"Index_Close",

"Target_Strike",

"CE_Symbol",

"CE_Open",
"CE_High",
"CE_Low",
"CE_Close",

"CE_Volume_Delta",
"CE_Cumulative_Vol",
"CE_Open_Interest",
"CE_OI_Change",

"CE_Delta",
"CE_Gamma",
"CE_Theta",
"CE_Vega",

"PE_Symbol",

"PE_Open",
"PE_High",
"PE_Low",
"PE_Close",

"PE_Volume_Delta",
"PE_Cumulative_Vol",
"PE_Open_Interest",
"PE_OI_Change",

"PE_Delta",
"PE_Gamma",
"PE_Theta",
"PE_Vega",

"ATM_Distance",

"IV_CE",
"IV_PE",

"PCR_Strike",

"VIX_Snapshot",

"Row_Hash",

"CE_Price_Source",
"PE_Price_Source"

)

VALUES %s

ON CONFLICT ("Row_Hash")
DO NOTHING;
"""


def _prepare_row(index_id, row):
    cleaned = [None if value == "" else value for value in row]
    return tuple([index_id] + cleaned)


class PostgresWriter:

    def __init__(self):
        pass

    def insert_batch(self, index_id, rows):

        if not rows:
            print(f"❌ {index_id}: Empty batch received")
            return False

        prepared_rows = [_prepare_row(index_id, row) for row in rows]
        conn = get_connection()

        try:
            with conn.cursor() as cursor:
                execute_values(
                    cursor,
                    INSERT_QUERY,
                    prepared_rows,
                    page_size=500
                )

            conn.commit()

            print(f"💾 {index_id}: inserted_rows={len(prepared_rows)}")

            return True

        except Exception as e:
            conn.rollback()
            print(f"❌ PostgreSQL insert failed for {index_id}: {e}")
            return False

        finally:

            release_connection(conn)