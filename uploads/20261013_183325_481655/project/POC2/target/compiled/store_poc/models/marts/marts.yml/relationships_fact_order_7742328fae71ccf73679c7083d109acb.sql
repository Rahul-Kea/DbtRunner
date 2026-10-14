
    
    

with child as (
    select payment_method_key as from_field
    from "simulation"."main"."fact_order"
    where payment_method_key is not null
),

parent as (
    select payment_method_key as to_field
    from "simulation"."main"."dim_payment_method"
)

select
    from_field

from child
left join parent
    on child.from_field = parent.to_field

where parent.to_field is null


