
-- Fixture for dim_customer
select 
    
    cast('C001' as character varying)
 as "customer_id", cast(null as character varying(256)) as "customer_name", cast(null as character varying(256)) as "customer_city"
union all
select 
    
    cast('C002' as character varying)
 as "customer_id", cast(null as character varying(256)) as "customer_name", cast(null as character varying(256)) as "customer_city"