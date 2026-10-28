Dont remove file, its a tmp working ground


loop + input channel from user/communication/tool response
{
    // agent can access and change anything within the brackets
    std_iteration(code)
}


def std_iteration(code)
{
    std_pre() // ex context rot detection, context trigger 
    push(invoke_code(code))
    std_post()
}