
    
    

with child as (
    select order_date as from_field
    from "simulation"."main"."fact_order"
    where order_date is not null
),

parent as (
    select order_date as to_field
    from "simulation"."main"."dim_date"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null


