"""Twitter Authentication Views"""
from urlparse import parse_qs

from urllib import urlencode

import oauth2 as oauth
import requests

from pyramid.httpexceptions import HTTPFound
from pyramid.settings import asbool

from velruse.api import AuthenticationComplete
from velruse.exceptions import AuthenticationDenied
from velruse.exceptions import ThirdPartyFailure


from velruse.utils import get_came_from

REQUEST_URL = 'https://api.twitter.com/oauth/request_token'
ACCESS_URL =  'https://api.twitter.com/oauth/access_token'


class TwitterAuthenticationComplete(AuthenticationComplete):
    """Twitter auth complete"""


def includeme(config):
    config.add_route("twitter_login", "/twitter/login")
    config.add_route("twitter_process", "/twitter/process",
                     use_global_views=True,
                     factory=twitter_process)
    config.add_view(twitter_login, route_name="twitter_login")
    settings = config.registry.settings
    settings['velruse.providers_infos']['velruse.providers.twitter']['login'] =   'twitter_login'
    settings['velruse.providers_infos']['velruse.providers.twitter']['process'] = 'twitter_process'


def twitter_login(request):
    """Initiate a Twitter login"""
    settings = request.registry.settings

    # Create the consumer and client, make the request
    consumer = oauth.Consumer(settings['velruse.twitter.consumer_key'],
                              settings['velruse.twitter.consumer_secret'])
    came_from = get_came_from(request)
    redirect_uri = request.route_url('twitter_process')
    if came_from:
        qs = urlencode({'end_point':came_from })
        if not '?' in redirect_uri:
            redirect_uri += '?'
        redirect_uri += qs 
    sigmethod = oauth.SignatureMethod_HMAC_SHA1()
    params = {'oauth_callback': redirect_uri}

    # We go through some shennanigans here to specify a callback url
    oauth_request = oauth.Request.from_consumer_and_token(consumer,
        http_url=REQUEST_URL, parameters=params)
    oauth_request.sign_request(sigmethod, consumer, None)
    r = requests.get(REQUEST_URL, headers=oauth_request.to_header())

    if r.status_code != 200:
        raise ThirdPartyFailure("Status %s: %s" % (r.status_code, r.content))
    request_token = oauth.Token.from_string(r.content)

    request.session['token'] = r.content

    # Send the user to twitter now for authorization
    if asbool(settings.get('velruse.twitter.authorize')):
        req_url = 'https://api.twitter.com/oauth/authorize'
    else:
        req_url = 'https://api.twitter.com/oauth/authenticate'
    oauth_request = oauth.Request.from_token_and_callback(
        token=request_token, http_url=req_url)
    return HTTPFound(location=oauth_request.to_url())


def twitter_process(request):
    """Process the Twitter redirect"""
    if 'denied' in request.GET:
        return AuthenticationDenied("User denied authentication")

    settings = request.registry.settings
    request_token = oauth.Token.from_string(request.session['token'])
    verifier = request.GET.get('oauth_verifier')
    if not verifier:
        raise ThirdPartyFailure("Oauth verifier not returned")
    request_token.set_verifier(verifier)

    # Create the consumer and client, make the request
    consumer = oauth.Consumer(settings['velruse.twitter.consumer_key'],
                              settings['velruse.twitter.consumer_secret'])

    client = oauth.Client(consumer, request_token)
    resp, content = client.request(ACCESS_URL, "POST")
    if resp['status'] != '200':
        raise ThirdPartyFailure("Status %s: %s" % (resp['status'], content))
    access_token = dict(parse_qs(content))

    # Setup the normalized contact info
    profile = {}
    profile['accounts'] = [{
        'domain':'twitter.com',
        'userid':access_token['user_id'][0]
    }]
    profile['displayName'] = access_token['screen_name'][0]
    profile['end_point'] = get_came_from(request)

    cred = {'oauthAccessToken': access_token['oauth_token'][0],
            'oauthAccessTokenSecret': access_token['oauth_token_secret'][0]}
    return TwitterAuthenticationComplete(profile=profile,
                                         credentials=cred)
