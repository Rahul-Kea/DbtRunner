
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select line_count
from "simulation"."main"."fact_order"
where line_count is null



  
  
      
    ) dbt_internal_test