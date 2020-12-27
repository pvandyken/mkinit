# -*- coding: utf-8 -*-
"""
Contains logic for formatting statically / dynamically extracted information
into the final product.
"""
from __future__ import absolute_import, division, print_function, unicode_literals
from os.path import join, exists
import textwrap
import logging
from mkinit import static_analysis as static


logger = logging.getLogger(__name__)


def _ensure_options(given_options=None):
    """
    Ensures dict contains all formatting options.

    Defaults are:
        with_attrs (bool): if True, generate module attribute from imports
            (Default: True)
        with_mods (bool): if True, generate module imports
            (Default: True)
        with_all (bool): if True, generate an __all__ variable
            (Default: True)
        relative (bool): if True, generate relative `.` imports
            (Default: False)

    """
    if given_options is None:
        given_options = {}
    default_options = {
        'with_attrs': True,
        'with_mods': True,
        'with_all': True,
        'relative': False,
        'lazy_import': False,
        'lazy_boilerplate': None,
        'use_black': False,
    }
    options = default_options.copy()
    for k in given_options.keys():
        if k not in default_options:
            raise KeyError('options got bad key={}'.format(k))
    options.update(given_options)
    return options


def _insert_autogen_text(modpath, initstr):
    """
    Creates new text for `__init__.py` containing the autogenerated code.

    If an `__init__.py` already exists in `modpath`, then it tries to
    intelligently insert the code without clobbering too much. See
    `_find_insert_points` for details on this process.
    """

    # Get path to init file so we can overwrite it
    init_fpath = join(modpath, '__init__.py')
    logger.debug('inserting initstr into: {!r}'.format(init_fpath))

    if exists(init_fpath):
        with open(init_fpath, 'r') as file_:
            lines = file_.readlines()
    else:
        lines = []

    startline, endline, init_indent = _find_insert_points(lines)
    initstr_ = _indent(initstr, init_indent) + '\n'

    new_lines = lines[:startline] + [initstr_] + lines[endline:]

    new_text = ''.join(new_lines).rstrip() + '\n'
    return init_fpath, new_text


def _find_insert_points(lines):
    r"""
    Searches for the points to insert autogenerated text between.

    If the `# <AUTOGEN_INIT>` directive exists, then it is preserved and new
    text is inserted after it. This text clobbers all other text until the `#
    <AUTOGEN_INIT>` is reached.

    If the explicit tags are not specified, mkinit will only clobber text after
    one of these patterns:
        * A line beginning with a (#) comment
        * A multiline (triple-quote) comment
        * A line beginning with "from __future__"
        * A line beginning with "__version__"

    If neither explicit tags or implicit patterns exist, all text is clobbered.

    Args:
        lines (list): lines of an `__init__.py` file.

    Returns:
        tuple: (int, int, str):
            insert points as starting line, ending line, and any required
            indentation.

    Examples:
        >>> lines = textwrap.dedent(
            '''
            preserved1 = True
            if True:
                # <AUTOGEN_INIT>
                clobbered2 = True
                # </AUTOGEN_INIT>
            preserved3 = True
            ''').strip('\n').split('\n')
        >>> start, end, indent = _find_insert_points(lines)
        >>> print(repr((start, end, indent)))
        (3, 4, '    ')

    Examples:
        >>> lines = textwrap.dedent(
            '''
            preserved1 = True
            __version__ = '1.0'
            clobbered2 = True
            ''').strip('\n').split('\n')
        >>> start, end, indent = _find_insert_points(lines)
        >>> print(repr((start, end, indent)))
        (2, 3, '')
    """
    startline = 0
    endline = len(lines)
    explicit_flag = False
    init_indent = ''

    # co-opt the xdoctest parser to break appart lines in the init file
    # This lets us correctly skip to the end of a multiline expression
    # A better solution might be to use the line-number aware parser
    # to search for AUTOGEN_INIT comments and other relevant structures.
    source_lines = ['>>> ' + p.rstrip('\n') for p in lines]
    try:
        ps1_lines, _ = static._locate_ps1_linenos(source_lines)
        # print('ps1_lines = {!r}'.format(ps1_lines))
    except IndexError:
        assert len(lines) == 0
        ps1_lines = []

    # Algorithm is similar to the old version, but we skip to the next PS1
    # line if we encounter an implicit code pattern.

    skipto = None

    def _tryskip(lineno):
        """ returns the next line to skip to if possible """

    implicit_patterns = (
        'from __future__', '__version__', '__submodules__',

        '__external__',
        '__private__',
        '__protected__',

        '#', '"""', "'''",
    )
    for lineno, line in enumerate(lines):
        if skipto is not None:
            if lineno != skipto:
                continue
            else:
                # print('SKIPPED TO = {!r}'.format(lineno))
                skipto = None
        if not explicit_flag:
            if line.strip().startswith(implicit_patterns):
                # print('[mkinit] RESPECTING LINE {}: {}'.format(lineno, line))
                startline = lineno + 1
                try:
                    # Try and skip to the end of the expression
                    # (if it is a multiline case)
                    idx = ps1_lines.index(lineno)
                    skipto = ps1_lines[idx + 1]
                    startline = skipto
                    # print('SKIPTO = {!r}'.format(skipto))
                except ValueError:
                    # print('NOT ON A PS1 LINE KEEP {}'.format(startline))
                    pass
                except IndexError:
                    # print('LAST LINE MOVING TO END {}'.format(startline))
                    startline = endline
        if line.strip().startswith('# <AUTOGEN_INIT>'):  # allow tags too
            # print('[mkinit] FOUND START TAG ON LINE {}: {}'.format(lineno, line))
            init_indent = line[:line.find('#')]
            explicit_flag = True
            startline = lineno + 1
        if explicit_flag and line.strip().startswith('# </AUTOGEN_INIT>'):
            # print('[mkinit] FOUND END TAG ON LINE {}: {}'.format(lineno, line))
            endline = lineno

    # print('startline = {}'.format(startline))
    # print('endline = {}'.format(endline))
    assert startline <= endline
    return startline, endline, init_indent


def _indent(text, indent='    '):
    new_text = indent + text.replace('\n', '\n' + indent)
    # remove whitespace on blank lines
    new_text = '\n'.join([line.rstrip() for line in new_text.split('\n')])
    return new_text


def _initstr(modname, imports, from_imports, explicit=set(), protected=set(),
             private=set(), options=None):
    r"""
    Calls the other string makers

    CommandLine:
        python -m mkinit.static_autogen _initstr

    Args:
        modname (str): the name of the module to generate the init str for

        imports (List[str]): list of module-level imports

        from_imports (List[Tuple[str, List[str]]]):
            List of submodules and their imported attributes

        options (dict): customize output

    CommandLine:
        python -m mkinit.formatting _initstr

    Example:
        >>> modname = 'foo'
        >>> imports = ['.bar', '.baz']
        >>> from_imports = [('.bar', ['func1', 'func2'])]
        >>> initstr = _initstr(modname, imports, from_imports)
        >>> print(initstr)
        from foo import bar
        from foo import baz
        <BLANKLINE>
        from foo.bar import (func1, func2,)
        <BLANKLINE>
        __all__ = ['bar', 'baz', 'func1', 'func2']

    Example:
        >>> modname = 'foo'
        >>> imports = ['.bar', '.baz']
        >>> from_imports = [('.bar', list(map(chr, range(97, 123))))]
        >>> initstr = _initstr(modname, imports, from_imports)
        >>> print(initstr)
        from foo import bar
        from foo import baz
        <BLANKLINE>
        from foo.bar import (a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p, q, r, s,
                             t, u, v, w, x, y, z,)
        <BLANKLINE>
        __all__ = ['a', 'b', 'bar', 'baz', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k',
                   'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x',
                   'y', 'z']

    Example:
        >>> modname = 'foo'
        >>> imports = ['.bar', '.baz']
        >>> from_imports = [('.bar', ['func1', 'func2'])]
        >>> options = {'lazy_import': 1, 'lazy_boilerplate': None}
        >>> initstr = _initstr(modname, imports, from_imports, options=options)
        >>> print(initstr)
        ...

        >>> options = {'lazy_import': 1, 'lazy_boilerplate': 'from importlib import lazy_import'}
        >>> initstr = _initstr(modname, imports, from_imports, options=options)
        >>> print(initstr.replace('\n\n', '\n'))
        from importlib import lazy_import
          __getattr__ = lazy_import(
              __name__,
              submodules={
                  'bar',
                  'baz',
              },
              submod_attrs={
                  'bar': [
                      'func1',
                      'func2',
                  ],
              },
        )
        def __dir__():
            return __all__
        __all__ = ['bar', 'baz', 'func1', 'func2']
    """
    options = _ensure_options(options)

    if options['relative']:
        modname = '.'

    explicit_exports = list(explicit)
    exposed_from_imports = []
    parts = []
    # if options.get('with_header', False):
    #     parts.append(_make_module_header())

    # map each submodule to its import statement
    submod_to_import = {e.lstrip('.'): e for e in imports}
    submodules = set(submod_to_import.keys())
    protected = set(protected)
    private = set(private)
    exposed_submodules = set()
    exposed_all = set()

    protected_submodules = submodules & protected

    if options.get('with_mods', True):
        exposed_submodules.update(submodules)
        exposed_all.update(submodules)

    exposed_submodules.update(protected_submodules)
    exposed_all.update(protected_submodules)

    from fnmatch import fnmatch
    # TODO: allow pattern matching here
    # step1: separate into explicit vs glob-pattern strings
    private_pats =  {p for p in private if '*' in p}
    private_set = private - private_pats

    protected_pats =  {p for p in protected if '*' in p}
    protected_set = protected - protected_pats

    _pp_pats = protected_pats | private_pats
    _pp_set = private_set | protected_set

    def _private_matches(x):
        x = x.lstrip('.')
        return x in private_set or any(fnmatch(x, pat) for pat in private_pats)

    def _pp_matches(x):
        # TODO: standardize how explicit vs submodules are handled
        x = x.lstrip('.')
        return x in _pp_set or any(fnmatch(x, pat) for pat in _pp_pats)

    raw_from_imports = [
        (m, sub) for m, sub in from_imports if not _pp_matches(m)
    ]

    if options.get('with_attrs', True):
        exposed_from_imports = raw_from_imports
    elif protected:
        exposed_from_imports = [
            (m, set(sub) & protected) for m, sub in raw_from_imports]
    exposed_from_imports = [
        (m, sub) for m, sub in exposed_from_imports if sub]
    exposed_all.update({
        n for m, sub in exposed_from_imports for n in sub
        if not _private_matches(n)
    })

    def append_part(new_part):
        """ appends a new part if it is nonempty """
        if new_part:
            if parts:
                # separate from previous parts with a newline
                parts.append('')
            parts.append(new_part)

    if options['lazy_import']:
        # NOTE: We are not using f-strings so the code can still be parsed
        # in older versions of python.
        default_lazy_boilerplate = textwrap.dedent(
            r'''

            def lazy_import(module_name, submodules, submod_attrs):
                """
                Boilerplate to define PEP 562 __getattr__ for lazy import
                https://www.python.org/dev/peps/pep-0562/
                """
                import sys
                import importlib
                import importlib.util
                all_funcs = []
                for mod, funcs in submod_attrs.items():
                    all_funcs.extend(funcs)
                name_to_submod = {
                    func: mod for mod, funcs in submod_attrs.items()
                    for func in funcs
                }

                def require(fullname):
                    if fullname in sys.modules:
                        return sys.modules[fullname]

                    spec = importlib.util.find_spec(fullname)
                    try:
                        module = importlib.util.module_from_spec(spec)
                    except Exception:
                        raise ImportError(
                            'Could not lazy import module {fullname}'.format(
                                fullname=fullname)) from None
                    loader = importlib.util.LazyLoader(spec.loader)

                    sys.modules[fullname] = module

                    # Make module with proper locking and add to sys.modules
                    loader.exec_module(module)

                    return module

                def __getattr__(name):
                    if name in submodules:
                        fullname = '{module_name}.{name}'.format(
                            module_name=module_name, name=name)
                        attr = require(fullname)
                    elif name in name_to_submod:
                        modname = name_to_submod[name]
                        module = importlib.import_module(
                            '{module_name}.{modname}'.format(
                                module_name=module_name, modname=modname)
                        )
                        attr = getattr(module, name)
                    else:
                        raise AttributeError(
                            'No {module_name} attribute {name}'.format(
                                module_name=module_name, name=name))
                    # Set module-level attribute so getattr is not called again
                    globals()[name] = attr
                    return attr
                return __getattr__
            '''
        ).rstrip('\n')
        template = textwrap.dedent(
            '''
            __getattr__ = lazy_import(
                __name__,
                submodules={submodules},
                submod_attrs={submod_attrs},
            )
            ''').rstrip('\n')
        submod_attrs = {}
        if exposed_from_imports:
            for submod, attrs in exposed_from_imports:
                submod = submod.lstrip('.')
                submod_attrs[submod] = attrs

        if explicit_exports:
            submodules = submodules
            print('submodules = {!r}'.format(submodules))
        else:
            submodules = set()

        # Currently this is the only use of ubelt, but repr2
        # is easier to use in testing than pprint, so perhaps
        # we can remove complexity and just use ubelt elsewhere
        import ubelt as ub
        initstr = template.format(
            submodules=ub.repr2(exposed_submodules).replace('\n', '\n    '),
            submod_attrs=ub.repr2(submod_attrs).replace('\n', '\n    '),
        )

        print('options = {!r}'.format(options))
        if options['lazy_boilerplate'] is None:
            append_part(default_lazy_boilerplate)
        else:
            # Customize lazy boilerplate
            append_part(options['lazy_boilerplate'])

        append_part(initstr.rstrip())
    else:
        if exposed_submodules:
            exposed_imports = [submod_to_import[k] for k in exposed_submodules]
            append_part(_make_imports_str(exposed_imports, modname))

        if exposed_from_imports:
            attr_part = _make_fromimport_str(exposed_from_imports, modname)
            append_part(attr_part)

    if options.get('with_all', True):
        if options['lazy_import']:
            append_part(textwrap.dedent(
                '''
                def __dir__():
                    return __all__
                ''').rstrip())
        exports_repr = ["'{}'".format(e)
                        for e in sorted(exposed_all)]
        rhs_body = ', '.join(exports_repr)
        packed = _packed_rhs_text('__all__ = [', rhs_body + ']')
        append_part(packed)

    initstr = '\n'.join([p for p in parts])

    if options['use_black']:
        try:
            import black
            initstr = black.format_str(
                initstr, mode=black.Mode(string_normalization=True))
        except ImportError:
            pass
    return initstr


def _make_imports_str(imports, rootmodname='.'):
    if False:
        imports_fmtstr = 'from {rootmodname} import %s'.format(
            rootmodname=rootmodname)
        return '\n'.join([imports_fmtstr % (name,) for name in imports])
    else:
        imports_fmtstr = 'from {rootmodname} import %s'.format(
            rootmodname=rootmodname)
        return '\n'.join([
            imports_fmtstr % (name.lstrip('.'))
            if name.startswith('.') else
            'import %s' % (name,)
            for name in imports
        ])


def _packed_rhs_text(lhs_text, rhs_text):
    """
    packs rhs text to have indentation that agrees with lhs text

    Example:
        >>> normname = 'this.is.a.module'
        >>> fromlist = ['func{}'.format(d) for d in range(10)]
        >>> indent = ''
        >>> lhs_text = indent + 'from {normname} import ('.format(
        >>>     normname=normname)
        >>> rhs_text = ', '.join(fromlist) + ',)'
        >>> packstr = _packed_rhs_text(lhs_text, rhs_text)
        >>> print(packstr)

        >>> normname = 'this.is.a.very.long.modnamethatwilkeepgoingandgoing'
        >>> fromlist = ['func{}'.format(d) for d in range(10)]
        >>> indent = ''
        >>> lhs_text = indent + 'from {normname} import ('.format(
        >>>     normname=normname)
        >>> rhs_text = ', '.join(fromlist) + ',)'
        >>> packstr = _packed_rhs_text(lhs_text, rhs_text)
        >>> print(packstr)

        >>> normname = 'this.is.a.very.long.modnamethatwilkeepgoingandgoingandgoingandgoingandgoingandgoing'
        >>> fromlist = ['func{}'.format(d) for d in range(10)]
        >>> indent = ''
        >>> lhs_text = indent + 'from {normname} import ('.format(
        >>>     normname=normname)
        >>> rhs_text = ', '.join(fromlist) + ',)'
        >>> packstr = _packed_rhs_text(lhs_text, rhs_text)
        >>> print(packstr)
    """
    # FIXME: the parens get broken up wrong
    # filler = '-' * (len(lhs_text) - 1) + ' '
    # fill_text = filler + rhs_text

    if 0:
        # options['use_black']:
        import black
        raw_text = lhs_text + rhs_text
        packstr = black.format_str(
            raw_text, mode=black.Mode(string_normalization=False))
        return packstr
    else:
        import re
        # not sure why this isn't 76? >= maybe?
        max_width = 79

        # This is a hacky heuristic that could perhaps be more robust?
        if len(lhs_text) > max_width * 0.7:
            newline_prefix = ' ' * 4
        else:
            newline_prefix = (' ' * len(lhs_text))

        raw_text = lhs_text + rhs_text
        wrapped_lines = textwrap.wrap(
            raw_text,
            break_long_words=False,
            width=79, initial_indent='',
            subsequent_indent=newline_prefix)
        packstr = '\n'.join(wrapped_lines)

        FIX_FORMAT = 1
        if FIX_FORMAT:
            regex = r'\s*'.join(list(map(re.escape, lhs_text.split(' '))))
            assert re.match(regex, lhs_text)
            match = re.search(regex, packstr)
            span = match.span()
            assert span[0] == 0
            wrapped_lhs = match.string[:span[1]]

            # If textwrap broke the LHS then do something slightly different
            if '\n' in wrapped_lhs:
                new_rhs = packstr[span[1]:]
                new_packstr = lhs_text + '\n' + newline_prefix + new_rhs
                packstr = new_packstr

    return packstr


def _make_fromimport_str(from_imports, rootmodname='.', indent=''):
    """
    Args:
        from_imports (list): each item is a tuple with module and a list of
            imported with_attrs.
        rootmodname (str): name of root module
        indent (str): initial indentation

    Example:
        >>> from_imports = [
        ...     ('.foo', list(map(chr, range(97, 123)))),
        ...     ('.bar', []),
        ...     ('.a_longer_package', list(map(chr, range(65, 91)))),
        ... ]
        >>> from_str = _make_fromimport_str(from_imports, indent=' ' * 8)
        >>> print(from_str)
        from .foo import (a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p, q, r,
                          s, t, u, v, w, x, y, z,)
        from .a_longer_package import (A, B, C, D, E, F, G, H, I, J, K, L, M,
                                       N, O, P, Q, R, S, T, U, V, W, X, Y, Z,)
    """
    if rootmodname == '.':  # nocover
        # dot is already taken care of in fmtstr
        rootmodname = ''
    def _pack_fromimport(tup):
        name, fromlist = tup[0], tup[1]

        if name.startswith('.'):
            normname = rootmodname + name
        else:
            normname = name

        if len(fromlist) > 0:
            lhs_text = indent + 'from {normname} import ('.format(
                normname=normname)
            rhs_text = ', '.join(fromlist) + ',)'
            packstr = _packed_rhs_text(lhs_text, rhs_text)
        else:
            packstr = ''
        return packstr

    parts = [_pack_fromimport(t) for t in from_imports]
    from_str = '\n'.join([p for p in parts if p])
    # Return unindented version for now
    from_str = textwrap.dedent(from_str)
    return from_str


if __name__ == '__main__':
    """
    CommandLine:
        python -m mkinit.formatting all
    """
    import xdoctest
    xdoctest.doctest_module(__file__)
