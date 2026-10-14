
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select order_total
from "simulation"."main"."fact_order"
where order_total is null



  
  
      
    ) dbt_internal_test