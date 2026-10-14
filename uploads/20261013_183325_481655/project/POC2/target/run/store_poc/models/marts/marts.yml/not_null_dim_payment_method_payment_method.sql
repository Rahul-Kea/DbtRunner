
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select payment_method
from "simulation"."main"."dim_payment_method"
where payment_method is null



  
  
      
    ) dbt_internal_test