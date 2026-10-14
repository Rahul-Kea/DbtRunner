
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select order_id
from "simulation"."main"."fact_order"
where order_id is null



  
  
      
    ) dbt_internal_test