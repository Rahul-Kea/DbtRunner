select distinct order_date
from {{ ref('stg_store_orders') }}
