
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select total_quantity
from "simulation"."main"."fact_order"
where total_quantity is null



  
  
      
    ) dbt_internal_test