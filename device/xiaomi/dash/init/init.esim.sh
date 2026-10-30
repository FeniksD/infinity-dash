#!/vendor/bin/sh

EID=$(/vendor/bin/mtkmtb -c 5:3 2>&1)

if echo "$EID" | grep -q "value=FAILED"; then
    STATE="disabled"
else
    STATE="enabled"
fi

setprop vendor.esim.state "$STATE"
