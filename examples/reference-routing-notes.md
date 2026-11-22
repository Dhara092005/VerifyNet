# VerifyNet sample reference: an IPv4 static route

This is an original teaching note for testing the reference-library feature. It is not a vendor manual and has not been verified on a running router.

## Interface address and gateway are different values

The interface address includes a prefix length, for example 10.10.0.1/30. A directly connected next-hop gateway is a distinct host on that subnet, for example 10.10.0.2, without a /prefix suffix.

## Reusable configuration

Keep the interface name, interface address, destination prefix, and next hop as separate template parameters. In the small command subset supported by VerifyNet, interface addressing belongs inside the interface block; the static route follows after exit.

## Inspecting failures

If a generated route uses the interface address including /30 as its gateway, the local parser rejects that value. If it uses a syntactically valid but incorrect gateway, the intent check rejects the mismatch. Both failures should be returned to the model as repair feedback.

## Source to consult

Official FRRouting static-route reference: https://docs.frrouting.org/en/latest/static.html

Passing the local checker does not establish that a real next-hop router exists or that packets reach their destination.
