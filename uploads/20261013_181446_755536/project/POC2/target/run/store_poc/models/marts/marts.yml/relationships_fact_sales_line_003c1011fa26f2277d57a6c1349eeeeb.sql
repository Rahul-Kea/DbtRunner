
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with child as (
    select payment_method as from_field
    from "simulation"."main"."fact_sales_line"
    where payment_method is not null
),

parent as (
    select payment_method as to_field
    from "simulation"."main"."dim_payment_method"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null



  
  
      
    ) dbt_internal_test