select distinct payment_method
from {{ ref('stg_store_orders') }}
