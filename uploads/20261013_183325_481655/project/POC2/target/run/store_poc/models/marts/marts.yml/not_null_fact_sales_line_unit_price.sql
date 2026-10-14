
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select unit_price
from "simulation"."main"."fact_sales_line"
where unit_price is null



  
  
      
    ) dbt_internal_test