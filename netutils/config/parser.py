"""Parsers for different network operating systems."""
# pylint: disable=no-member,super-with-arguments,invalid-overridden-method,raise-missing-from,invalid-overridden-method,inconsistent-return-statements,super-with-arguments,redefined-argument-from-local,no-else-break,useless-super-delegation,too-many-lines

import re
from collections import namedtuple

from netutils.banner import normalise_delimiter_caret_c

ConfigLine = namedtuple("ConfigLine", "config_line,parents")


class BaseConfigParser:  # pylint: disable=too-few-public-methods
    """Base class for parsers."""

    comment_chars = ["!"]
    banner_start = ["banner", "vacant-message"]

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        self.config = config
        self._config = None
        self._current_parents = ()
        self.generator_config = (line for line in self.config_lines_only.splitlines())
        self.config_lines = []
        self.build_config_relationship()

    def config_lines_only(self):
        """Remove lines not related to config."""
        raise NotImplementedError


class BaseSpaceConfigParser(BaseConfigParser):
    """Base parser class for config syntax that demarcates using spaces/indentation."""

    comment_chars = ["!"]
    banner_start = ["banner", "vacant-message"]

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        self._indent_level = 0
        super(BaseSpaceConfigParser, self).__init__(config)

    @property
    def indent_level(self):
        """Count the number of spaces a config line is indented."""
        return self._indent_level

    @indent_level.setter
    def indent_level(self, value):
        self._indent_level = value

    def is_banner_end(self, line):
        """Determine if line ends the banner config.

        Args:
            line (str): The current config line in iteration.

        Returns:
            bool: True if line ends banner, else False.
        """
        if self.banner_end in line:
            return True
        return False

    def is_banner_start(self, line):
        """Determine if the line starts a banner config.

        Args:
            line (str): The current config line in iteration.

        Returns:
            bool: True if line starts banner, else False.
        """
        for banner_start in self.banner_start:
            if line.lstrip().startswith(banner_start):
                return True
        return False

    def is_comment(self, line):
        """Determine if line is a comment.

        Args:
            line (str): A config line from the device.

        Returns:
            bool: True if line is a comment, else False.

        Example:
            >>> BaseSpaceConfigParser("interface Ethernet1/1").is_comment("interface Ethernet1/1")
            False
            >>> BaseSpaceConfigParser("!").is_comment("!")
            True
            >>>
        """
        for comment_char in self.comment_chars:
            if line.lstrip().startswith(comment_char):
                return True
        return False

    @property
    def config_lines_only(self):
        """Remove spaces and comments from config lines.

        Returns:
            str: The non-space and non-comment lines from ``config``.

        Example:
            >>> config = '''!
            ... aaa group server tacacs+ auth
            ...  server 10.1.1.1
            ...  server 10.2.2.2
            ...
            ... !
            ... '''
            >>> config_parser = BaseSpaceConfigParser(config)
            >>> print(config_parser.config_lines_only)
            aaa group server tacacs+ auth
             server 10.1.1.1
             server 10.2.2.2
            >>>
        """
        if self._config is None:
            config_lines = (
                line.rstrip()
                for line in self.config.splitlines()
                if line and not self.is_comment(line) and not line.isspace()
            )
            self._config = "\n".join(config_lines)
        return self._config

    @staticmethod
    def get_leading_space_count(config_line):
        r"""Determine how many spaces the ``config_line`` is indented.

        Args:
           config_line (str): A line of text in the config.

        Returns:
            int: The number of leading spaces.

        Example:
            >>> config = '''interface GigabitEthernet1\n description link to ISP'''
            >>> config_line = " description link to ISP"
            >>> indent_level = BaseSpaceConfigParser(config).get_leading_space_count(config_line)
            >>> indent_level
            1
            >>>
        """
        return len(config_line) - len(config_line.lstrip())

    def _remove_parents(self, line, current_spaces):
        """Remove parents from ``self._curent_parents`` based on indent levels.

        Args:
            config_line (str): A line of text in the config.

        Returns:
            tuple: The config lines parent config lines.
        """
        deindent_level = 1
        try:
            previous_parent = self._current_parents[-1]
            previous_indent = self.get_leading_space_count(previous_parent)
            while previous_indent > current_spaces:
                deindent_level += 1
                previous_parent = self._current_parents[-deindent_level]
                previous_indent = self.get_leading_space_count(previous_parent)
        except IndexError:
            raise IndexError(f"\nValidate the first line does not begin with a space\n{line}\n")
        parents = self._current_parents[:-deindent_level] or (self._current_parents[0],)
        return parents

    def _build_banner(self, config_line):
        """Handle banner config lines.

        Args:
            config_line (str): The start of the banner config.

        Returns:
            str: The next configuration line in the configuration text.
            None: When banner end is the end of the config text.

        Raises:
            ValueError: When the parser is unable to identify the End of the Banner.
        """
        self._update_config_lines(config_line)
        self._current_parents += (config_line,)
        banner_config = []
        for line in self.generator_config:
            if not self.is_banner_end(line):
                banner_config.append(line)
            else:
                line = normalise_delimiter_caret_c(self.banner_end, line)
                banner_config.append(line)
                line = "\n".join(banner_config)
                if line.endswith("^C"):
                    banner, end, _ = line.rpartition("^C")
                    line = banner.rstrip() + end
                self._update_config_lines(line)
                self._current_parents = self._current_parents[:-1]
                try:
                    return next(self.generator_config)
                except StopIteration:
                    return None

        raise ValueError("Unable to parse banner end.")

    def _build_nested_config(self, line):
        """Handle building child config sections.

        Args:
            line (str): A configuration line from the configuration text.

        Returns:
            str: The next top-level configuration line in the configuration text.
            None: When the last line of configuration text is a nested configuration line.

        Raises:
            IndexError: When the number of parents does not match the expected deindent level.
        """
        self._update_config_lines(line)
        for line in self.generator_config:
            if not line[0].isspace():
                self._current_parents = ()
                self.indent_level = 0
                return line

            spaces = self.get_leading_space_count(line)
            if spaces == self.indent_level:
                pass
            elif spaces > self.indent_level:
                previous_config = self.config_lines[-1]
                self._current_parents += (previous_config.config_line,)
            else:
                self._current_parents = self._remove_parents(line, spaces)

            if spaces != self.indent_level:
                self.indent_level = spaces

            if self.is_banner_start(line):
                line = self._build_banner(line)
                if line is None or not line[0].isspace():
                    self._current_parents = ()
                    self.indent_level = 0
                    return line

            self._update_config_lines(line)

    def _update_config_lines(self, config_line):
        """Add a ``ConfigLine`` object to ``self.config_lines``.

        Args:
            config_line (str): The current config line being evaluated.

        Returns:
            None
        """
        entry = ConfigLine(config_line, self._current_parents)
        self.config_lines.append(entry)

    def build_config_relationship(self):
        r"""Parse text tree of config lines and their parents.

        Example:
            >>> config = (
            ...     "interface Ethernet1/1\n"
            ...     "  vlan 10\n"
            ...     "  no shutdown"
            ...     "interface Ethernet1/2\n"
            ...     "  shutdown\n"
            ... )
            >>> config_tree = BaseSpaceConfigParser(config)
            >>> config_tree.build_config_relationship() == \
            ... [
            ...     ConfigLine(config_line='interface Ethernet1/1', parents=()),
            ...     ConfigLine(config_line='  vlan 10', parents=('interface Ethernet1/1',)),
            ...     ConfigLine(config_line='  no shutdowninterface Ethernet1/2', parents=('interface Ethernet1/1',)),
            ...     ConfigLine(config_line='  shutdown', parents=('interface Ethernet1/1',))
            ... ]
            True
        """
        for line in self.generator_config:
            if not line[0].isspace():
                self._current_parents = ()
                if self.is_banner_start(line):
                    line = self._build_banner(line)
            else:
                previous_config = self.config_lines[-1]
                self._current_parents = (previous_config.config_line,)
                self.indent_level = self.get_leading_space_count(line)
                if not self.is_banner_start(line):
                    line = self._build_nested_config(line)
                else:
                    line = self._build_banner(line)
                    if line is not None and line[0].isspace():
                        line = self._build_nested_config(line)
                    else:
                        self._current_parents = ()

            if line is None:
                break
            elif self.is_banner_start(line):
                line = self._build_banner(line)

            self._update_config_lines(line)
        return self.config_lines


class BaseBraceConfigParser(BaseConfigParser):
    """Base parser class for config syntax that demarcates using braces."""

    multiline_delimiters = []

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        super(BaseBraceConfigParser, self).__init__(config)

    @property
    def config_lines_only(self):
        """Remove trailing spaces and empty lines from config lines.

        Returns:
            str: The non-space lines from ``config``.
        """
        config_lines = [line.rstrip() for line in self.config.splitlines() if line and not line.isspace()]
        return "\n".join(config_lines)

    def build_config_relationship(self):
        r"""Parse text tree of config lines and their parents.

        Example:
            >>> config = '''auth ldap system-auth {
            ...         port ldaps
            ...         servers { ams-lda01.ntc.com }
            ...     }
            ...     auth partition Common {
            ...         description "Repository for system objects and shared objects."
            ...     }
            ...     auth password-policy { }'''
            >>> config_tree = BaseBraceConfigParser(config)
            >>> config_tree.build_config_relationship() == \
            ... [
            ...     ConfigLine(config_line='auth ldap system-auth {', parents=()),
            ...     ConfigLine(config_line='        port ldaps', parents=('auth ldap system-auth {',)),
            ...     ConfigLine(config_line='        servers { ams-lda01.ntc.com }', parents=('auth ldap system-auth {',)),
            ...     ConfigLine(config_line='    }', parents=('auth ldap system-auth {',)),
            ...     ConfigLine(config_line='    auth partition Common {', parents=()),
            ...     ConfigLine(config_line='        description "Repository for system objects and shared objects."', parents=('    auth partition Common {',)), ConfigLine(config_line='    }', parents=('    auth partition Common {',)),
            ...     ConfigLine(config_line='    auth password-policy { }', parents=())
            ... ]
            True
        """
        for line in self.generator_config:
            self.config_lines.append(ConfigLine(line, self._current_parents))
            line_end = line[-1]
            if line.endswith("{"):
                self._current_parents += (line,)
            elif line.lstrip() == "}":
                self._current_parents = self._current_parents[:-1]
            elif line_end in self.multiline_delimiters and line.count(line_end) == 1:
                self._current_parents += (line,)
                self._build_multiline_config(line_end)

        return self.config_lines

    def _build_multiline_config(self, delimiter):
        r"""Build config sections between characters demarcating multiline strings.

        Args:
            delimiter (str): The text to look for to end multiline config.

        Returns:
            ConfigLine: The multiline string text that was added to ``self.config_lines``.

        Example:
            >>> config = (
            ...     'sys syslog {\n'
            ...     '    include "\n'
            ...     '        filter f_local0 {\n'
            ...     '        facility(local0) and not match(\"DEBUG");\n'
            ...     '    "\n'
            ...     '}'
            ... )
            >>> parser = BaseBraceConfigParser(config)
            >>> # '    include "' started a multiline config
            >>> parser.config_lines == \
            ... [
            ...     ConfigLine(config_line='sys syslog {', parents=()),
            ...     ConfigLine(config_line='    include "', parents=('sys syslog {',)),
            ...     ConfigLine(config_line='        filter f_local0 {', parents=('sys syslog {',)),
            ...     ConfigLine(config_line='        facility(local0) and not match("DEBUG");', parents=('sys syslog {', '        filter f_local0 {')),
            ...     ConfigLine(config_line='    "', parents=('sys syslog {', '        filter f_local0 {')),
            ...     ConfigLine(config_line='}', parents=('sys syslog {', '        filter f_local0 {'))
            ... ]
            True
        """
        multiline_config = []
        for line in self.generator_config:
            multiline_config.append(line)
            if line.lstrip() == delimiter:
                multiline_entry = ConfigLine("\n".join(multiline_config), self._current_parents)
                self.config_lines.append(multiline_entry)
                self._current_parents = self._current_parents[:-1]
                return multiline_entry


class CiscoConfigParser(BaseSpaceConfigParser):
    """Cisco Implementation of ConfigParser Class."""

    regex_banner = re.compile(r"^(banner\s+\S+|\s*vacant-message)\s+(?P<banner_delimiter>\^C|.)")

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        self._banner_end = None
        super(CiscoConfigParser, self).__init__(config)

    def _build_banner(self, config_line):
        """Handle banner config lines.

        Args:
            config_line (str): The start of the banner config.

        Returns:
            str: The next configuration line in the configuration text.
            None: When banner end is the end of the config text.

        Raises:
            ValueError: When the parser is unable to identify the End of the Banner.
        """
        if self.is_banner_one_line(config_line):
            self._update_config_lines(config_line)
            try:
                return next(self.generator_config)
            except StopIteration:
                return None
        return super(CiscoConfigParser, self)._build_banner(config_line)

    @staticmethod
    def is_banner_one_line(config_line):
        """Determine if all banner config is on one line."""
        _, delimeter, banner = config_line.partition("^C")
        # Based on NXOS configs, the banner delimeter is ignored until another char is used
        banner_config_start = banner.lstrip(delimeter)
        if delimeter not in banner_config_start:
            return False
        return True

    def is_banner_start(self, line):
        """Determine if the line starts a banner config."""
        state = super(CiscoConfigParser, self).is_banner_start(line)
        if state:
            self.banner_end = line
        return state

    @property
    def banner_end(self):
        """Demarcate End of Banner char(s)."""
        return self._banner_end

    @banner_end.setter
    def banner_end(self, banner_start_line):
        banner_parsed = self.regex_banner.match(banner_start_line)
        if not banner_parsed:
            raise ValueError("There was an error parsing your banner, the end of the banner could not be found")
        self._banner_end = banner_parsed.groupdict()["banner_delimiter"]


class IOSConfigParser(CiscoConfigParser, BaseSpaceConfigParser):
    """Cisco IOS implementation of ConfigParser Class."""

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        self.unique_config_lines = set()
        self.same_line_children = set()
        super(IOSConfigParser, self).__init__(config)

    def _build_banner(self, config_line):
        """Handle banner config lines.

        Args:
            config_line (str): The start of the banner config.

        Returns:
            str: The next configuration line in the configuration text.
            None: When banner end is the end of the config text.

        Raises:
            ValueError: When the parser is unable to identify the End of the Banner.
        """
        config_line = normalise_delimiter_caret_c(self.banner_end, config_line)
        return super(IOSConfigParser, self)._build_banner(config_line)

    def _update_same_line_children_configs(self):
        """Update parents in ``self.config_lines`` per ``self.same_line_children``."""
        new_config_lines = []
        for line in self.config_lines:
            if line in self.same_line_children:
                previous_line = new_config_lines[-1]
                previous_config_line = previous_line.config_line
                current_parents = previous_line.parents + (previous_config_line,)
                line = ConfigLine(line.config_line, current_parents)
            new_config_lines.append(line)
        self.config_lines = new_config_lines

    def _update_config_lines(self, config_line):
        """Add a ``ConfigLine`` object to ``self.config_lines``.

        In addition to adding entries to config_lines, this also updates:
          * self.same_line_children
          * self.unique_config_lines

        Args:
            config_line (str): The current config line being evaluated.

        Returns:
            None
        """
        super(IOSConfigParser, self)._update_config_lines(config_line)
        entry = self.config_lines[-1]
        if entry in self.unique_config_lines:
            self.same_line_children.add(entry)
        self.unique_config_lines.add(entry)

    def build_config_relationship(self):
        r"""Parse text tree of config lines and their parents.

        Example:
            >>> config = '''
            ... interface Ethernet1/1
            ...   vlan 10
            ...   no shutdown
            ... interface Ethernet1/2
            ...   shutdown'''
            >>> config_tree = IOSConfigParser(str(config))
            >>> config_tree.build_config_relationship() == \
            ... [
            ...     ConfigLine(config_line='interface Ethernet1/1', parents=()),
            ...     ConfigLine(config_line='  vlan 10', parents=('interface Ethernet1/1',)),
            ...     ConfigLine(config_line='  no shutdown', parents=('interface Ethernet1/1',)),
            ...     ConfigLine(config_line='interface Ethernet1/2', parents=()),
            ...     ConfigLine(config_line='  shutdown', parents=('interface Ethernet1/2',))
            ... ]
            True
        """
        super(IOSConfigParser, self).build_config_relationship()
        self._update_same_line_children_configs()
        return self.config_lines


class NXOSConfigParser(CiscoConfigParser, BaseSpaceConfigParser):
    """NXOS implementation of ConfigParser Class."""

    regex_banner = re.compile(r"^banner\s+\S+\s+(?P<banner_delimiter>\S)")

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        self.unique_config_lines = set()
        self.same_line_children = set()
        super(NXOSConfigParser, self).__init__(config)

    def _build_banner(self, config_line):
        """Handle banner config lines.

        Args:
            config_line (str): The start of the banner config.

        Returns:
            str: The next configuration line in the configuration text.
            None: When banner end is the end of the config text.

        Raises:
            ValueError: When the parser is unable to identify the End of the Banner.
        """
        config_line = normalise_delimiter_caret_c(self.banner_end, config_line)
        return super(NXOSConfigParser, self)._build_banner(config_line)


class EOSConfigParser(BaseSpaceConfigParser):
    """EOSConfigParser implementation fo ConfigParser Class."""

    banner_end = "EOF"

    def _build_banner(self, config_line):
        """Handle banner config lines.

        Args:
            config_line (str): The start of the banner config.

        Returns:
            str: The next configuration line in the configuration text.
            None: When banner end is the end of the config text.

        Raises:
            ValueError: When the parser is unable to identify the End of the Banner.
        """
        self._update_config_lines(config_line)
        self._current_parents += (config_line,)
        banner_config = []
        for line in self.generator_config:
            if not self.is_banner_end(line):
                banner_config.append(line)
            else:
                banner_config.append(line)
                line = "\n".join(banner_config)
                self._update_config_lines(line)
                self._current_parents = self._current_parents[:-1]
                try:
                    return next(self.generator_config)
                except StopIteration:
                    return None
        raise ValueError("Unable to parse banner end.")


class AIREOSConfigParser(CiscoConfigParser, BaseSpaceConfigParser):
    """AireOSConfigParser implementation fo ConfigParser Class."""

    banner_start = []

    def _build_banner(self, config_line):
        raise NotImplementedError()


class LINUXConfigParser(BaseSpaceConfigParser):
    """Linux config parser."""

    comment_chars = ["#"]


class F5ConfigParser(BaseBraceConfigParser):
    """F5ConfigParser implementation fo ConfigParser Class."""

    multiline_delimiters = ['"']

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        super().__init__(self._clean_config_f5(config))

    def _clean_config_f5(self, config_text):  # pylint: disable=no-self-use
        """Removes all configuration items with 'ltm rule'.

        iRules are essentially impossible to parse with the lack of uniformity,
        therefore, this method ensures they are not included in ``self.config``.

        Args:
            config_text (str): The entire config as a string.

        Returns:
            str: The sanitized config with all iRules (ltm rule) stanzas removed.
        """
        config_split = config_text.split("ltm rule")
        if len(config_split) > 1:
            start_config = config_split[0]
            end_config = config_split[-1]
            _, ltm, clean_config = end_config.partition("ltm")
            final_config = start_config + ltm + clean_config
        else:
            final_config = config_text
        return final_config

    def build_config_relationship(self):
        r"""Parse text tree of config lines and their parents.

        Example:
            >>> config = '''apm resource webtop-link aShare {
            ...     application-uri http://funshare.example.com
            ...     customization-group a_customization_group
            ... }
            ... apm sso form-based portal_ext_sso_form_based {
            ...     form-action /Citrix/Example/ExplicitAuth/LoginAttempt
            ...     form-field "LoginBtn Log+On
            ... StateContext "
            ...     form-password password
            ...     form-username username
            ...     passthru true
            ...     start-uri /Citrix/Example/ExplicitAuth/Login*
            ...     success-match-type cookie
            ...     success-match-value CtxsAuthId
            ... }
            ... '''
            >>>
            >>> config_tree = F5ConfigParser(config)
            >>> print(config_tree.build_config_relationship())
            [ConfigLine(config_line='apm resource webtop-link aShare {', parents=()), ConfigLine(config_line='    application-uri http://funshare.example.com', parents=('apm resource webtop-link aShare {',)), ConfigLine(config_line='    customization-group a_customization_group', parents=('apm resource webtop-link aShare {',)), ConfigLine(config_line='}', parents=('apm resource webtop-link aShare {',)), ConfigLine(config_line='apm sso form-based portal_ext_sso_form_based {', parents=()), ConfigLine(config_line='    form-action /Citrix/Example/ExplicitAuth/LoginAttempt', parents=('apm sso form-based portal_ext_sso_form_based {',)), ConfigLine(config_line='    form-field "LoginBtn Log+On\nStateContext "', parents=('apm sso form-based portal_ext_sso_form_based {',)), ConfigLine(config_line='    form-password password', parents=()), ConfigLine(config_line='    form-username username', parents=()), ConfigLine(config_line='    passthru true', parents=()), ConfigLine(config_line='    start-uri /Citrix/Example/ExplicitAuth/Login*', parents=()), ConfigLine(config_line='    success-match-type cookie', parents=()), ConfigLine(config_line='    success-match-value CtxsAuthId', parents=()), ConfigLine(config_line='}', parents=())]
        """
        for line in self.generator_config:
            self.config_lines.append(ConfigLine(line, self._current_parents))
            line_end = line[-1]
            if line.endswith("{"):
                self._current_parents += (line,)
            elif line.lstrip() == "}":
                self._current_parents = self._current_parents[:-1]
            elif any(
                delimiters in self.multiline_delimiters and line.count(delimiters) == 1
                for delimiters in self.multiline_delimiters
            ):
                for delimiter in self.multiline_delimiters:
                    if line.count(delimiter) == 1:
                        self._build_multiline_single_configuration_line(delimiter, line)
            elif line_end in self.multiline_delimiters and line.count(line_end) == 1:
                self._current_parents += (line,)
                self._build_multiline_config(line_end)

        return self.config_lines

    def _build_multiline_single_configuration_line(self, delimiter, prev_line):
        r"""Concatenate Multiline strings between delimiter when newlines causes string to traverse multiple lines.

        Args:
            delimiter (str): The text to look for to end multiline config.
            prev_line (str): The text from the previously analyzed line.

        Returns:
            ConfigLine: The multiline string text that was added to ``self.config_lines``.

        Example:
            config = '''apm resource webtop-link aShare {
                application-uri http://funshare.example.com
                customization-group a_customization_group
            }
            apm sso form-based portal_ext_sso_form_based {
                form-action /Citrix/Example/ExplicitAuth/LoginAttempt
            >>>
            >>> config = '''apm resource webtop-link aShare {
            ...     application-uri http://funshare.example.com
            ...     customization-group a_customization_group
            ... }
            ... apm sso form-based portal_ext_sso_form_based {
            ...     form-action /Citrix/Example/ExplicitAuth/LoginAttempt
            ...     form-field "LoginBtn Log+On
            ... StateContext "
            ...     form-password password
            ...     form-username username
            ...     passthru true
            ...     start-uri /Citrix/Example/ExplicitAuth/Login*
            ...     success-match-type cookie
            ...     success-match-value CtxsAuthId
            ... }
            ... '''
            >>>
            >>>
            >>> config_tree = F5ConfigParser(str(config))
            >>> print(config_tree.build_config_relationship())
            [ConfigLine(config_line='apm resource webtop-link aShare {', parents=()), ConfigLine(config_line='    application-uri http://funshare.example.com', parents=('apm resource webtop-link aShare {',)), ConfigLine(config_line='    customization-group a_customization_group', parents=('apm resource webtop-link aShare {',)), ConfigLine(config_line='}', parents=('apm resource webtop-link aShare {',)), ConfigLine(config_line='apm sso form-based portal_ext_sso_form_based {', parents=()), ConfigLine(config_line='    form-action /Citrix/Example/ExplicitAuth/LoginAttempt', parents=('apm sso form-based portal_ext_sso_form_based {',)), ConfigLine(config_line='    form-field "LoginBtn Log+On\nStateContext "', parents=('apm sso form-based portal_ext_sso_form_based {',)), ConfigLine(config_line='    form-password password', parents=()), ConfigLine(config_line='    form-username username', parents=()), ConfigLine(config_line='    passthru true', parents=()), ConfigLine(config_line='    start-uri /Citrix/Example/ExplicitAuth/Login*', parents=()), ConfigLine(config_line='    success-match-type cookie', parents=()), ConfigLine(config_line='    success-match-value CtxsAuthId', parents=()), ConfigLine(config_line='}', parents=())]
        """
        multiline_config = [prev_line]
        for line in self.generator_config:
            multiline_config.append(line)
            if line.endswith(delimiter):
                multiline_entry = ConfigLine("\n".join(multiline_config), self._current_parents)
                self.config_lines[-1] = multiline_entry
                self._current_parents = self._current_parents[:-1]
                return multiline_entry


class JunosConfigParser(BaseSpaceConfigParser):
    """Junos config parser."""

    comment_chars = []
    banner_start = []


class ASAConfigParser(CiscoConfigParser):
    """Cisco ASA implementation of ConfigParser Class."""

    comment_chars = ["!", ":"]

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        self.unique_config_lines = set()
        self.same_line_children = set()
        super(ASAConfigParser, self).__init__(config)

    def _update_config_lines(self, config_line):
        """Add a ``ConfigLine`` object to ``self.config_lines``.

        In addition to adding entries to config_lines, this also updates:
          * self.same_line_children
          * self.unique_config_lines

        Args:
            config_line (str): The current config line being evaluated.

        Returns:
            None
        """
        super(ASAConfigParser, self)._update_config_lines(config_line)
        entry = self.config_lines[-1]
        if entry in self.unique_config_lines:
            self.same_line_children.add(entry)
        self.unique_config_lines.add(entry)

    def build_config_relationship(self):
        r"""Parse text tree of config lines and their parents.

        Example:
            >>> config = '''
            ... interface Management0/0
            ...  management-only
            ...  nameif Management
            ...  security-level 100
            ...  ip address 10.1.1.10 255.255.255.0'''
            >>> config_tree = ASAConfigParser(str(config))
            >>> config_tree.build_config_relationship() == \
            ... [
            ...     ConfigLine(config_line="interface Management0/0", parents=()),
            ...     ConfigLine(config_line=" management-only", parents=("interface Management0/0",)),
            ...     ConfigLine(config_line=" nameif Management", parents=("interface Management0/0",)),
            ...     ConfigLine(config_line=" security-level 100", parents=("interface Management0/0",)),
            ...     ConfigLine(config_line=" ip address 10.1.1.10 255.255.255.0", parents=("interface Management0/0",)),
            ... ]
            True
        """
        for line in self.generator_config:
            if not line[0].isspace():
                self._current_parents = ()
            else:
                previous_config = self.config_lines[-1]
                self._current_parents = (previous_config.config_line,)
                self.indent_level = self.get_leading_space_count(line)
                if line is not None and line[0].isspace():
                    line = self._build_nested_config(line)
                else:
                    self._current_parents = ()

            if line is None:
                break

            self._update_config_lines(line)

        return self.config_lines


class FortinetConfigParser(BaseSpaceConfigParser):
    """Fortinet Fortios config parser."""

    comment_chars = []
    banner_start = []

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        self.uncommon_data = self._get_uncommon_lines(config)
        super(FortinetConfigParser, self).__init__(config)

    def is_end_next(self, line):  # pylint: disable=no-self-use
        """Determine if line has 'end' or 'next' in it.

        Args:
            line (str): A config line from the device.

        Returns:
            bool: True if line has 'end' or 'next', else False.

        Example:
            >>> FortinetConfigParser("config system virtual-switch").is_end_next("config system virtual-switch")
            False
            >>> FortinetConfigParser("end").is_end_next("end")
            True
            >>>
        """
        for end_next in ["end", "next"]:
            if line.lstrip() == end_next:
                return True
        return False

    def _parse_out_offending(self, config):  # pylint: disable=no-self-use
        """Preprocess out strings that offend the normal spaced configuration syntax.

        Args:
            config (str): full config as a string.
        """
        # This will grab everything between quotes after the 'set buffer' sub-command.
        # Its explicitly looking for "\n to end the captured data.  This is to support html
        # data that is supported in Fortinet config with double quotes within the html.
        pattern = r"(config system replacemsg.*(\".*\")\n)(\s{4}set\sbuffer\s\"[\S\s]*?\"\n)"
        return re.sub(pattern, r"\1    [\2]\n", config)

    @property
    def config_lines_only(self):
        """Remove spaces and comments from config lines.

        Returns:
            str: The non-space and non-comment lines from ``config``.
        """
        # Specific to fortinet to remove uncommon data patterns for use later in _build_nested_config.
        self.config = self._parse_out_offending(self.config)
        if self._config is None:
            config_lines = (
                line.rstrip()
                for line in self.config.splitlines()
                if line and not self.is_comment(line) and not line.isspace() and not self.is_end_next(line)
            )
            self._config = "\n".join(config_lines)
        return self._config

    def _get_uncommon_lines(self, config):  # pylint: disable=no-self-use
        """Regex to find replacemsg lines which can contain html/css data.

        Args:
            config (str): Original config before parsing.

        Returns:
            dict: dictionary with replace message name as key, html/css data as value.
        """
        pattern = r"(config system replacemsg.*\n)(\s{4}set\sbuffer\s\"[\S\s]*?\"\n)"
        regex_result = re.findall(pattern, config)
        result = {}
        for group_match in regex_result:
            result.update({group_match[0].split('"')[1]: group_match[1]})
        return result

    def _build_nested_config(self, line):
        """Handle building child config sections.

        Args:
            line (str): A configuration line from the configuration text.

        Returns:
            str: The next top-level configuration line in the configuration text.
            None: When the last line of configuration text is a nested configuration line.

        Raises:
            IndexError: When the number of parents does not match the expected deindent level.
        """
        if "[" in line:
            line = self.uncommon_data.get(line.split('"')[1])
        self._update_config_lines(line)
        for line in self.generator_config:
            if not line[0].isspace():
                self._current_parents = ()
                self.indent_level = 0
                return line

            spaces = self.get_leading_space_count(line)
            if spaces == self.indent_level:
                pass
            elif spaces > self.indent_level:
                previous_config = self.config_lines[-1]
                self._current_parents += (previous_config.config_line,)
            else:
                self._current_parents = self._remove_parents(line, spaces)

            if spaces != self.indent_level:
                self.indent_level = spaces

            self._update_config_lines(line)


class NokiaConfigParser(BaseSpaceConfigParser):
    """Nokia SrOS config parser."""

    comment_chars = ["#"]
    banner_start = []

    def __init__(self, config):
        """Create ConfigParser Object.

        Args:
            config (str): The config text to parse.
        """
        super(NokiaConfigParser, self).__init__(config)

    def _is_section_title(self, line):  # pylint: disable=no-self-use
        """Determine if line is a section title in banner.

        Args:
            line (str): A config line from the device.

        Returns:
            bool: True if line is a sectiont, else False.
        """
        if re.match(r"^echo\s\".+\"", string=line):
            return True
        return False

    def _get_section_title(self, line):  # pylint: disable=no-self-use
        """Determine section title from banner.

        Args:
            line (str): A config line from the device that has been found to be a section title.

        Returns:
            str|bool: The section's title from the section banner, else False.
        """
        section_title = re.match(r"^echo\s\"(?P<section_name>.+)\"", string=line)
        if section_title:
            return section_title.group("section_name")
        return False

    @property
    def config_lines_only(self):
        """Remove spaces and comments from config lines.

        Returns:
            str: The non-space and non-comment lines from ``config``.
        """
        if self._config is None:
            config_lines = []
            for line in self.config.splitlines():
                if line and not self.is_comment(line) and not line.isspace():
                    if self._is_section_title(line):
                        config_lines.append(self._get_section_title(line))
                    else:
                        config_lines.append(line.rstrip())
            self._config = "\n".join(config_lines)
        return self._config
