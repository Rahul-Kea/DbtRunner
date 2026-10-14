
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select quantity
from "simulation"."main"."fact_sales_line"
where quantity is null



  
  
      
    ) dbt_internal_test