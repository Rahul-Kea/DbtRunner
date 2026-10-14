select distinct
    product_id,
    product_name,
    product_category
from {{ ref('stg_store_orders') }}
