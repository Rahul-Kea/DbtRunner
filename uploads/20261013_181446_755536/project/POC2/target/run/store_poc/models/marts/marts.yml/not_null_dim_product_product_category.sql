
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select product_category
from "simulation"."main"."dim_product"
where product_category is null



  
  
      
    ) dbt_internal_test