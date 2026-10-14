
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select store_key
from "simulation"."main"."fact_order"
where store_key is null



  
  
      
    ) dbt_internal_test