select distinct
    store_id,
    store_name
from {{ ref('stg_store_orders') }}
