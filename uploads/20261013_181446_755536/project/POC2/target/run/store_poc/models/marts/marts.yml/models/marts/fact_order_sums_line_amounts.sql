
    -- Build actual result given inputs
with dbt_internal_unit_test_actual as (
  select
    "order_id","order_date","customer_id","store_id","payment_method","line_count","total_quantity","order_total", 'actual' as "actual_or_expected"
  from (
    with __dbt__cte__stg_store_orders as (

-- Fixture for stg_store_orders
select 
    
    cast(1001 as INTEGER)
 as "order_id", 
    
    cast('2025-01-03' as DATE)
 as "order_date", 
    
    cast('C001' as character varying)
 as "customer_id", cast(null as character varying(256)) as "customer_name", cast(null as character varying(256)) as "customer_city", cast(null as character varying(256)) as "product_id", cast(null as character varying(256)) as "product_name", cast(null as character varying(256)) as "product_category", cast(null as DECIMAL(10,2)) as "unit_price", 
    
    cast(2 as INTEGER)
 as "quantity", 
    
    cast('S01' as character varying)
 as "store_id", cast(null as character varying(256)) as "store_name", 
    
    cast('Card' as character varying)
 as "payment_method", 
    
    cast(25.0 as DECIMAL(10,2))
 as "line_amount"
union all
select 
    
    cast(1001 as INTEGER)
 as "order_id", 
    
    cast('2025-01-03' as DATE)
 as "order_date", 
    
    cast('C001' as character varying)
 as "customer_id", cast(null as character varying(256)) as "customer_name", cast(null as character varying(256)) as "customer_city", cast(null as character varying(256)) as "product_id", cast(null as character varying(256)) as "product_name", cast(null as character varying(256)) as "product_category", cast(null as DECIMAL(10,2)) as "unit_price", 
    
    cast(3 as INTEGER)
 as "quantity", 
    
    cast('S01' as character varying)
 as "store_id", cast(null as character varying(256)) as "store_name", 
    
    cast('Card' as character varying)
 as "payment_method", 
    
    cast(18.0 as DECIMAL(10,2))
 as "line_amount"
union all
select 
    
    cast(1002 as INTEGER)
 as "order_id", 
    
    cast('2025-01-04' as DATE)
 as "order_date", 
    
    cast('C002' as character varying)
 as "customer_id", cast(null as character varying(256)) as "customer_name", cast(null as character varying(256)) as "customer_city", cast(null as character varying(256)) as "product_id", cast(null as character varying(256)) as "product_name", cast(null as character varying(256)) as "product_category", cast(null as DECIMAL(10,2)) as "unit_price", 
    
    cast(1 as INTEGER)
 as "quantity", 
    
    cast('S01' as character varying)
 as "store_id", cast(null as character varying(256)) as "store_name", 
    
    cast('Card' as character varying)
 as "payment_method", 
    
    cast(7.5 as DECIMAL(10,2))
 as "line_amount"
),  __dbt__cte__dim_date as (

-- Fixture for dim_date
select 
    
    cast('2025-01-03' as DATE)
 as "order_date"
union all
select 
    
    cast('2025-01-04' as DATE)
 as "order_date"
),  __dbt__cte__dim_customer as (

-- Fixture for dim_customer
select 
    
    cast('C001' as character varying)
 as "customer_id", cast(null as character varying(256)) as "customer_name", cast(null as character varying(256)) as "customer_city"
union all
select 
    
    cast('C002' as character varying)
 as "customer_id", cast(null as character varying(256)) as "customer_name", cast(null as character varying(256)) as "customer_city"
),  __dbt__cte__dim_store as (

-- Fixture for dim_store
select 
    
    cast('S01' as character varying)
 as "store_id", cast(null as character varying(256)) as "store_name"
),  __dbt__cte__dim_payment_method as (

-- Fixture for dim_payment_method
select 
    
    cast('Card' as character varying)
 as "payment_method"
) select
    s.order_id,
    d.order_date,
    s.customer_id,
    s.store_id,
    s.payment_method,
    count(*) as line_count,
    sum(s.quantity) as total_quantity,
    sum(s.line_amount) as order_total
from __dbt__cte__stg_store_orders as s
join __dbt__cte__dim_date as d
    on s.order_date = d.order_date
join __dbt__cte__dim_customer as c
    on s.customer_id = c.customer_id
join __dbt__cte__dim_store as st
    on s.store_id = st.store_id
join __dbt__cte__dim_payment_method as pm
    on s.payment_method = pm.payment_method
group by
    s.order_id,
    d.order_date,
    s.customer_id,
    s.store_id,
    s.payment_method
  ) _dbt_internal_unit_test_actual
),
-- Build expected result
dbt_internal_unit_test_expected as (
  select
    "order_id", "order_date", "customer_id", "store_id", "payment_method", "line_count", "total_quantity", "order_total", 'expected' as "actual_or_expected"
  from (
    select 
    
    cast(1001 as INTEGER)
 as "order_id", 
    
    cast('2025-01-03' as DATE)
 as "order_date", 
    
    cast('C001' as character varying)
 as "customer_id", 
    
    cast('S01' as character varying)
 as "store_id", 
    
    cast('Card' as character varying)
 as "payment_method", 
    
    cast(2 as BIGINT)
 as "line_count", 
    
    cast(5 as HUGEINT)
 as "total_quantity", 
    
    cast(43.0 as DECIMAL(38,2))
 as "order_total"
union all
select 
    
    cast(1002 as INTEGER)
 as "order_id", 
    
    cast('2025-01-04' as DATE)
 as "order_date", 
    
    cast('C002' as character varying)
 as "customer_id", 
    
    cast('S01' as character varying)
 as "store_id", 
    
    cast('Card' as character varying)
 as "payment_method", 
    
    cast(1 as BIGINT)
 as "line_count", 
    
    cast(1 as HUGEINT)
 as "total_quantity", 
    
    cast(7.5 as DECIMAL(38,2))
 as "order_total"
  ) _dbt_internal_unit_test_expected
)
-- Union actual and expected results
select * from dbt_internal_unit_test_actual
union all
select * from dbt_internal_unit_test_expected