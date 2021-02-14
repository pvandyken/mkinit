"""
Statically ports utilities from ubelt needed by mkinit.
"""


def autogen_mkint_utils():
    import ubelt as ub

    # Uses netharn closer until it is ported to a standalone module
    from liberator import closer

    closer = closer.Closer()

    from ubelt import util_import

    closer.add_dynamic(util_import.split_modpath)
    closer.add_dynamic(util_import.modpath_to_modname)
    closer.add_dynamic(util_import.modname_to_modpath)

    closer.expand(["ubelt"])
    text = closer.current_sourcecode()
    print(text)

    import redbaron

    new_baron = redbaron.RedBaron(text)
    new_names = [n.name for n in new_baron.node_list if n.type in ["class", "def"]]

    import mkinit
    from mkinit import util
    from mkinit.util import util_import  # NOQA

    old_baron = redbaron.RedBaron(open(mkinit.util.util_import.__file__, "r").read())

    old_names = [n.name for n in old_baron.node_list if n.type in ["class", "def"]]

    set(old_names) - set(new_names)
    set(new_names) - set(old_names)

    prefix = ub.codeblock(
        '''
        # -*- coding: utf-8 -*-
        """
        This file was autogenerated based on code in ubelt
        """
        from __future__ import print_function, division, absolute_import, unicode_literals
        '''
    )

    code = prefix + "\n" + text + "\n"
    print(code)

    fpath = ub.expandpath("~/code/mkinit/mkinit/util/util_import.py")

    open(fpath, "w").write(code)
