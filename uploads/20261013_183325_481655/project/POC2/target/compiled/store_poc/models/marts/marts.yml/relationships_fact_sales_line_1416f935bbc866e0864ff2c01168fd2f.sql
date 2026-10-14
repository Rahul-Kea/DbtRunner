
    
    

with child as (
    select store_key as from_field
    from "simulation"."main"."fact_sales_line"
    where store_key is not null
),

parent as (
    select store_key as to_field
    from "simulation"."main"."dim_store"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null


