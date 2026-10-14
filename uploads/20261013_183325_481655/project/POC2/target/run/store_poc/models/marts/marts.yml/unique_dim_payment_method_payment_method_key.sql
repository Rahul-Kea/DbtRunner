
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    payment_method_key as unique_field,
    count(*) as n_records

from "simulation"."main"."dim_payment_method"
where payment_method_key is not null
group by payment_method_key
having count(*) > 1



  
  
      
    ) dbt_internal_test