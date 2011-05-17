from __future__ import absolute_import
import email
import pycurl
import logging
import urllib

from grab.grab import GrabError

logger = logging.getLogger('grab')

# @lorien: I do not understand these signals. Maybe you?

# We should ignore SIGPIPE when using pycurl.NOSIGNAL - see
# the libcurl tutorial for more info.

# http://curl.haxx.se/mail/curlpython-2005-06/0004.html
# http://curl.haxx.se/mail/lib-2010-03/0114.html

#CURLOPT_NOSIGNAL
#Pass a long. If it is 1, libcurl will not use any functions that install signal handlers or any functions that cause signals to be sent to the process. This option is mainly here to allow multi-threaded unix applications to still set/use all timeout options etc, without risking getting signals. (Added in 7.10)
#If this option is set and libcurl has been built with the standard name resolver, timeouts will not occur while the name resolve takes place. Consider building libcurl with c-ares support to enable asynchronous DNS lookups, which enables nice timeouts for name resolves without signals.

try:
    import signal
    from signal import SIGPIPE, SIG_IGN
    try:
        signal.signal(SIGPIPE, SIG_IGN)
    except ValueError:
        # Ignore the exception
        # ValueError: signal only works in main thread
        pass
except ImportError:
    pass


class Extension(object):
    export_attributes = ['head_processor', 'body_processor', 'debug_processor',
                         'process_config', 'extract_cookies', 'prepare_response']
    transport = True

    def extra_init(self, grab):
        grab.curl = pycurl.Curl()

    def extra_reset(self, grab):
        grab.response_head_chunks = []
        grab.response_body_chunks = []

    def head_processor(self, chunk):
        """
        Process head of response.
        """

        if self.config['nohead']:
            return 0
        self.response_head_chunks.append(chunk)
        return len(chunk)

    def body_processor(self, chunk):
        """
        Process body of response.
        """

        if self.config['nobody']:
            return 0
        self.response_body_chunks.append(chunk)
        return len(chunk)

    def debug_processor(self, _type, text):
        """
        Parse request headers and save to ``self.request_headers``
        """

        if _type == pycurl.INFOTYPE_HEADER_OUT:
            text = '\n'.join(text.splitlines()[1:])
            self.request_headers = dict(email.message_from_string(text))

    def process_config(self):
        """
        Setup curl instance with values from ``self.config``.
        """

        url = self.config['url']
        if isinstance(url, unicode):
            url = url.encode('utf-8')
        self.curl.setopt(pycurl.URL, url)
        self.curl.setopt(pycurl.FOLLOWLOCATION, 1)
        self.curl.setopt(pycurl.MAXREDIRS, 5)
        self.curl.setopt(pycurl.CONNECTTIMEOUT, self.config['connect_timeout'])
        self.curl.setopt(pycurl.TIMEOUT, self.config['timeout'])
        self.curl.setopt(pycurl.NOSIGNAL, 1)
        self.curl.setopt(pycurl.WRITEFUNCTION, self.body_processor)
        self.curl.setopt(pycurl.HEADERFUNCTION, self.head_processor)
        self.curl.setopt(pycurl.USERAGENT, self.config['user_agent'])

        if self.config['debug']:
            self.curl.setopt(pycurl.VERBOSE, 1)
            self.curl.setopt(pycurl.DEBUGFUNCTION, self.debug_processor)

        # Ignore SSL errors
        self.curl.setopt(pycurl.SSL_VERIFYPEER, 0)
        self.curl.setopt(pycurl.SSL_VERIFYHOST, 0)

        method = self.config['method']
        if method:
            method = method.upper()
        else:
            if self.config['payload'] or self.config['post']:
                method = 'POST'
            else:
                method = 'GET'

        if method == 'POST':
            self.curl.setopt(pycurl.POST, 1)
            if self.config['payload']:
                self.curl.setopt(pycurl.POSTFIELDS, self.config['payload'])
            elif self.config['post']:
                post_data = self.urlencode(self.config['post'])
                self.curl.setopt(pycurl.POSTFIELDS, post_data)
        elif method == 'PUT':
            self.curl.setopt(pycurl.PUT, 1)
            self.curl.setopt(pycurl.READFUNCTION, StringIO(self.config['payload']).read) 
        elif method == 'DELETE':
            self.curl.setopt(pycurl.CUSTOMREQUEST, 'delete')
        else:
            self.curl.setopt(pycurl.HTTPGET, 1)
        
        headers = self.default_headers
        if self.config['headers']:
            headers.update(self.config['headers'])
        header_tuples = [str('%s: %s' % x) for x\
                         in headers.iteritems()]
        self.curl.setopt(pycurl.HTTPHEADER, header_tuples)


        # CURLOPT_COOKIELIST
        # Pass a char * to a cookie string. Cookie can be either in Netscape / Mozilla format or just regular HTTP-style header (Set-Cookie: ...) format.
        # If cURL cookie engine was not enabled it will enable its cookie engine.
        # Passing a magic string "ALL" will erase all cookies known by cURL. (Added in 7.14.1)
        # Passing the special string "SESS" will only erase all session cookies known by cURL. (Added in 7.15.4)
        # Passing the special string "FLUSH" will write all cookies known by cURL to the file specified by CURLOPT_COOKIEJAR. (Added in 7.17.1)

        if self.config['reuse_cookies']:
            # Setting empty string will activate curl cookie engine
            self.curl.setopt(pycurl.COOKIELIST, '')
        else:
            self.curl.setopt(pycurl.COOKIELIST, 'ALL')


        # CURLOPT_COOKIE
        # Pass a pointer to a zero terminated string as parameter. It will be used to set a cookie in the http request. The format of the string should be NAME=CONTENTS, where NAME is the cookie name and CONTENTS is what the cookie should contain.
        # If you need to set multiple cookies, you need to set them all using a single option and thus you need to concatenate them all in one single string. Set multiple cookies in one string like this: "name1=content1; name2=content2;" etc.
        # Note that this option sets the cookie header explictly in the outgoing request(s). If multiple requests are done due to authentication, followed redirections or similar, they will all get this cookie passed on.
        # Using this option multiple times will only make the latest string override the previous ones. 

        if self.config['cookies']:
            chunks = []
            for key, value in self.config['cookies'].iteritems():
                if isinstance(key, unicode):
                    key = key.encode(charset)
                if isinstance(value, unicode):
                    value = value.encode(charset)
                key = urllib.quote_plus(key)
                value = urllib.quote_plus(value)
                chunks.append('%s=%s;' % (key, value))
            self.curl.setopt(pycurl.COOKIE, ''.join(chunks))

        if self.config['referer']:
            self.curl.setopt(pycurl.REFERER, str(self.config['referer']))

        if self.config['proxy']:
            self.curl.setopt(pycurl.PROXY, str(self.config['proxy'])) 

        if self.config['proxy_userpwd']:
            self.curl.setopt(pycurl.PROXYUSERPWD, self.config['proxy_userpwd'])

        # PROXYTYPE
        # Pass a long with this option to set type of the proxy. Available options for this are CURLPROXY_HTTP, CURLPROXY_HTTP_1_0 (added in 7.19.4), CURLPROXY_SOCKS4 (added in 7.15.2), CURLPROXY_SOCKS5, CURLPROXY_SOCKS4A (added in 7.18.0) and CURLPROXY_SOCKS5_HOSTNAME (added in 7.18.0). The HTTP type is default. (Added in 7.10) 

        if self.config['proxy_type']:
            ptype = getattr(pycurl, 'PROXYTYPE_%s' % self.config['proxy_type'].upper())
            self.curl.setopt(pycurl.PROXYTYPE, ptype)

        if self.config['proxy']:
            if self.config['proxy_userpwd']:
                auth = ' with authorization'
            else:
                auth = ''
            proxy_info = ' via %s proxy of type %s%s' % (
                self.config['proxy'], self.config['proxy_type'], auth)
        else:
            proxy_info = ''

        logger.debug('[%02d] %s %s%s' % (self.request_counter, method, self.config['url'], proxy_info))

        if self.config['encoding']:
            self.curl.setopt(pycurl.ENCODING, self.config['encoding'])

    def extract_cookies(self):
        """
        Extract cookies.
        """

        # Example of line:
        # www.google.com\tFALSE\t/accounts/\tFALSE\t0\tGoogleAccountsLocale_session\ten
        cookies = {}
        for line in self.curl.getinfo(pycurl.INFO_COOKIELIST):
            chunks = line.split('\t')
            cookies[chunks[-2]] = chunks[-1]
        return cookies


    def request(self, grab):
        try:
            grab.curl.perform()
        except pycurl.error, ex:
            # CURLE_WRITE_ERROR
            # An error occurred when writing received data to a local file, or
            # an error was returned to libcurl from a write callback.
            # This is expected error and we should ignore it
            if 23 == ex[0]:
                pass
            else:
                raise GrabError(ex[0], ex[1])

    def prepare_response(self):
        self.response.head = ''.join(self.response_head_chunks)
        self.response.body = ''.join(self.response_body_chunks)
        self.response.parse()
        self.response.cookies = self.extract_cookies()
        self.response.code = self.curl.getinfo(pycurl.HTTP_CODE)
        self.response.time = self.curl.getinfo(pycurl.TOTAL_TIME)
        self.response.url = self.curl.getinfo(pycurl.EFFECTIVE_URL)

