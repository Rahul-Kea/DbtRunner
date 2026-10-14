
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select product_key
from "simulation"."main"."fact_sales_line"
where product_key is null



  
  
      
    ) dbt_internal_test