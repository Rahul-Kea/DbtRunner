select
    s.order_id,
    d.order_date,
    s.customer_id,
    s.product_id,
    s.store_id,
    s.payment_method,
    s.quantity,
    s.unit_price,
    s.line_amount
from {{ ref('stg_store_orders') }} as s
join {{ ref('dim_date') }} as d
    on s.order_date = d.order_date
join {{ ref('dim_customer') }} as c
    on s.customer_id = c.customer_id
join {{ ref('dim_product') }} as p
    on s.product_id = p.product_id
join {{ ref('dim_store') }} as st
    on s.store_id = st.store_id
join {{ ref('dim_payment_method') }} as pm
    on s.payment_method = pm.payment_method
