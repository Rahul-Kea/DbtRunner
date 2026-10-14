select distinct
    customer_id,
    customer_name,
    customer_city
from {{ ref('stg_store_orders') }}
