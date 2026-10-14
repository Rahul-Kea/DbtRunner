select
    s.order_id,
    d.order_date,
    s.customer_id,
    s.store_id,
    s.payment_method,
    count(*) as line_count,
    sum(s.quantity) as total_quantity,
    sum(s.line_amount) as order_total
from {{ ref('stg_store_orders') }} as s
join {{ ref('dim_date') }} as d
    on s.order_date = d.order_date
join {{ ref('dim_customer') }} as c
    on s.customer_id = c.customer_id
join {{ ref('dim_store') }} as st
    on s.store_id = st.store_id
join {{ ref('dim_payment_method') }} as pm
    on s.payment_method = pm.payment_method
group by
    s.order_id,
    d.order_date,
    s.customer_id,
    s.store_id,
    s.payment_method
