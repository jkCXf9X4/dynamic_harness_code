

the setup:

    root = runtime.spawn(
        "parent",
        driver=MockDriver.single(
            "child_code = " + repr(child_block) + "\n"
            "c = spawn('child task', driver=MockDriver.single(child_code))\n"
            "comp = await_(c)\n"
            "result = complete('root saw: ' + comp.summary)\n"
        ),
    )

, it seems a bit crude

what if the agent always injected a snippet with the call arguments to make it explicit, like:

def call(self: Agent):
    code