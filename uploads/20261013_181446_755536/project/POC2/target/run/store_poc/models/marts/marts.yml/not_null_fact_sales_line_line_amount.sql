
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select line_amount
from "simulation"."main"."fact_sales_line"
where line_amount is null



  
  
      
    ) dbt_internal_test