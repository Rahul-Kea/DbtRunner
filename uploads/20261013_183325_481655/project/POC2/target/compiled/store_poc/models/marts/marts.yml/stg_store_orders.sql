
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