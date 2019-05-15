##
# See the file COPYRIGHT for copyright information.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##

"""
Incident Management System Klein application.
"""

from __future__ import absolute_import

from functools import wraps
from typing import Any, Callable, Iterable, Optional, Union

from hyperlink import URL

from klein import Klein

from twisted.logger import Logger
from twisted.python.failure import Failure
from twisted.web import http
from twisted.web.iweb import IRenderable, IRequest
from twisted.web.template import renderElement

from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import RequestRedirect

from ims import __version__ as version
from ims.auth import NotAuthenticatedError, NotAuthorizedError
from ims.config import URLs
from ims.dms import DMSError
from ims.element.redirect import RedirectPage
from ims.ext.klein import (
    ContentType, HeaderName, KleinRenderable, KleinRouteMethod
)


__all__ = (
    "Router",
    "queryValue",
    "queryValues",
)


log = Logger()


def renderResponse(f: KleinRouteMethod) -> KleinRouteMethod:
    """
    Decorator to ensure that the returned response is rendered, if applicable.
    Needed because L{Klein.handle_errors} doesn't do rendering for you.
    """
    @wraps(f)
    def wrapper(
        self: Any, request: IRequest, *args: Any, **kwargs: Any
    ) -> KleinRenderable:
        response = f(self, request, *args, **kwargs)

        if IRenderable.providedBy(response):
            return renderElement(request, response)

        return response

    return wrapper


def redirect(
    request: IRequest, location: URL, origin: Optional[str] = None
) -> KleinRenderable:
    """
    Perform a redirect.
    """
    if origin is not None:
        try:
            location = location.set(origin, request.uri.decode("utf-8"))
        except ValueError:
            return badRequestResponse(request, "Invalid origin URI")

    log.debug(
        "Redirect {source} -> {destination}",
        source=request.uri.decode("utf-8"), destination=location.asText(),
    )
    url = location.asText().encode("utf-8")

    request.setHeader(HeaderName.contentType.value, ContentType.html.value)
    request.setHeader(HeaderName.location.value, url)
    request.setResponseCode(http.FOUND)

    return RedirectPage(location=location)


#
# Error responses
#

def noContentResponse(
    request: IRequest, etag: Optional[str] = None
) -> KleinRenderable:
    """
    Respond with no content.
    """
    request.setResponseCode(http.NO_CONTENT)
    if etag is not None:
        request.setHeader(HeaderName.etag.value, etag)
    return b""


def textResponse(request: IRequest, message: str) -> KleinRenderable:
    """
    Respond with the given text.
    """
    request.setHeader(HeaderName.contentType.value, ContentType.text.value)
    request.setHeader(
        HeaderName.etag.value, str(hash(message)).encode("ascii")
    )
    return message.encode("utf-8")


def notFoundResponse(request: IRequest) -> KleinRenderable:
    """
    Respond with a NOT FOUND status.
    """
    log.debug("Resource not found: {request.uri}", request=request)

    request.setResponseCode(http.NOT_FOUND)
    return textResponse(request, "Not found")


def methodNotAllowedResponse(request: IRequest) -> KleinRenderable:
    """
    Respond with a METHOD NOT ALLOWED status.
    """
    log.debug(
        "Method {request.method} not allowed for resource: {request.uri}",
        request=request
    )

    request.setResponseCode(http.NOT_ALLOWED)
    return textResponse(request, "HTTP method not allowed")


def forbiddenResponse(request: IRequest) -> KleinRenderable:
    """
    Respond with a FORBIDDEN status.
    """
    log.debug(
        "Forbidden resource for user {user}: {request.uri}",
        request=request, user=getattr(request, "user", None)
    )

    request.setResponseCode(http.FORBIDDEN)
    return textResponse(request, "Permission denied")


def badRequestResponse(
    request: IRequest, message: Optional[str] = None
) -> KleinRenderable:
    """
    Respond with a BAD REQUEST status.
    """
    log.debug(
        "Bad request for resource: {request.uri}: {message}",
        request=request, message=message
    )

    request.setResponseCode(http.BAD_REQUEST)
    if message is None:
        message = "Bad request"
    else:
        message = str(message)
    return textResponse(request, message)


def invalidQueryResponse(
    request: IRequest, arg: str, value: Optional[str] = None
) -> KleinRenderable:
    """
    Respond with a BAD REQUEST status due to an invalid query.
    """
    if value is None:
        return badRequestResponse(
            request, f"Invalid query: missing parameter {arg}"
        )
    else:
        return badRequestResponse(request, f"Invalid query: {arg}={value}")


def internalErrorResponse(
    request: IRequest, message: Optional[str] = None
) -> KleinRenderable:
    """
    Respond with an INTERNAL SERVER ERROR status.
    """
    log.critical(
        "Internal error for resource: {request.uri}: {message}",
        request=request, message=message
    )

    request.setResponseCode(http.INTERNAL_SERVER_ERROR)
    if message is None:
        message = "Internal error"
    else:
        message = f"{message}"
    return textResponse(request, message)


#
# Query arguments
#

def queryValue(
    request: IRequest, name: str, default: Optional[str] = None
) -> Optional[str]:
    """
    Look up the value of a query parameter with the given name in the
    given request.

    @param request: The request to look into.

    @param name: The name of the query parameter to find a value for.

    @param default: The default value to return if no query parameter
        specified by C{name} is found in C{request}.

    @return: The value of the query parameter specified by C{name}, or
        C{default} if there no such query parameter.
        If more than one value is found, return the last value found.
    """
    values = request.args.get(name.encode("utf-8"))

    if values is None:
        return default

    if len(values) > 0:
        return values[-1].decode("utf-8")
    else:
        return default


def queryValues(
    request: IRequest, name: str, default: Iterable[str] = ()
) -> Iterable[str]:
    """
    Look up the values of a query parameter with the given name in the
    given request.

    @param request: The request to look into.

    @param name: The name of the query parameter to find a value for.

    @param default: The default values to return if no query parameter
        specified by C{name} is found in C{request}.

    @return: The values of the query parameter specified by C{name}, or
        C{default} if there no such query parameter.
    """
    values = request.args.get(name)

    if values is None:
        return default

    return (a.decode("utf-8") for a in values)


#
# Router
#

class Router(Klein):
    """
    Klein router.
    """

    def __init__(self) -> None:
        super().__init__()
        self._registerHandlers()


    def route(
        self, url: Union[str, URL], *args: Any, **kwargs: Any
    ) -> Callable[[KleinRouteMethod], KleinRouteMethod]:
        """
        See :meth:`Klein.route`.
        """
        superRoute = super().route

        if isinstance(url, URL):
            url = url.asText()

        def decorator(f: KleinRouteMethod) -> KleinRouteMethod:
            @superRoute(url, *args, **kwargs)
            @wraps(f)
            def wrapper(
                app: Any, request: IRequest, *args: Any, **kwargs: Any
            ) -> KleinRenderable:
                request.setHeader(
                    HeaderName.server.value,
                    f"Incident Management System/{version}",
                )

                # Capture authentication info if sent by the client, (ie. it's
                # been previously asked to authenticate), so we can log it, but
                # don't require authentication.
                app.config.authProvider.authenticateRequest(
                    request, optional=True
                )

                return f(app, request, *args, **kwargs)

            return wrapper
        return decorator


    def _registerHandlers(self) -> None:
        @self.handle_errors(RequestRedirect)
        @renderResponse
        def requestRedirectError(
            app: Any, request: IRequest, failure: Failure
        ) -> KleinRenderable:
            """
            Redirect.
            """
            url = URL.fromText(failure.value.args[0])
            return redirect(request, url)


        @self.handle_errors(NotFound)
        @renderResponse
        def notFoundError(
            app: Any, request: IRequest, failure: Failure
        ) -> KleinRenderable:
            """
            Not found.
            """
            # Require authentication.
            # This is because exposing what resources do or do not exist can
            # expose information that was not meant to be exposed.
            app.config.authProvider.authenticateRequest(request)
            return notFoundResponse(request)


        @self.handle_errors(MethodNotAllowed)
        @renderResponse
        def methodNotAllowedError(
            app: Any, request: IRequest, failure: Failure
        ) -> KleinRenderable:
            """
            HTTP method not allowed.
            """
            # Require authentication.
            # This is because exposing what resources do or do not exist can
            # expose information that was not meant to be exposed.
            app.config.authProvider.authenticateRequest(request)
            return methodNotAllowedResponse(request)


        @self.handle_errors(NotAuthorizedError)
        @renderResponse
        def notAuthorizedError(
            app: Any, request: IRequest, failure: Failure
        ) -> KleinRenderable:
            """
            Not authorized.
            """
            return forbiddenResponse(request)


        @self.handle_errors(NotAuthenticatedError)
        @renderResponse
        def notAuthenticatedError(
            app: Any, request: IRequest, failure: Failure
        ) -> KleinRenderable:
            """
            Not authenticated.
            """
            requestedWith = request.getHeader("X-Requested-With")
            if requestedWith is not None:
                if requestedWith == "XMLHttpRequest":
                    return forbiddenResponse(request)

            element = redirect(request, URLs.login, origin="o")
            return renderElement(request, element)


        @self.handle_errors(DMSError)
        @renderResponse
        def dmsError(
            app: Any, request: IRequest, failure: Failure
        ) -> KleinRenderable:
            """
            DMS error.
            """
            log.critical("DMS error: {error}", error=failure)
            return internalErrorResponse(request)


        @self.handle_errors
        @renderResponse
        def unknownError(
            app: Any, request: IRequest, failure: Failure
        ) -> KleinRenderable:
            """
            Deal with a request error caught by Klein.
            """
            # This logs the failure traceback for debugging.
            # Klein normally will also display the traceback in the response.
            # We don't do that for a few reasons:
            #  - It's a poor security practice to explain to an attacker what
            #    exactly is causing an internal error.
            #  - Most users don't know what to do with that inforrmation.
            #  - The admins should be able to find the errors in the logs.
            #  - Klein doing that is a developer feature; developers can also
            #    watch the logs.
            #  - The traceback is emitted after whatever else was sent with the
            #    request, which often means that it displays like a total mess
            #    in a browser, and that's just pitiful.
            log.failure("Request failed", failure)
            return internalErrorResponse(request)
