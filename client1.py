'''
23 July 2017
svakulenko

Simple Twitter stream topic matcher via ElasticSearch
'''

from tweepy.streaming import StreamListener
from tweepy import Stream, API, OAuthHandler

from elasticsearch import Elasticsearch

from settings import *


# set up Twitter connection
auth_handler = OAuthHandler(APP_KEY, APP_SECRET)
auth_handler.set_access_token(OAUTH_TOKEN, OAUTH_TOKEN_SECRET)
twitter_client = API(auth_handler)

# set up ES connection
es = Elasticsearch()


multi = {
            "query": {
                "multi_match" : {
                    "type": "most_fields",
                    "fields": ["title", 'description', 'narrative']
                }
            }
        }


def tokenize_in_es(text, index=INDEX):
    '''
    Produce tokens from text via ES english analyzer
    '''
    tokens = es.indices.analyze(index=index, analyzer='english', text=text)
    return [token['token'] for token in tokens['tokens']]


def search_all(query, threshold=40, explain=False, index=INDEX):
    '''
    Search tweet through topics in ES index
    '''
    # search in all 3 facets of the topic with equal weights,
    request = multi
    request['query']['multi_match']['query'] = query
    results = es.search(index=index, body=request, doc_type='topics', explain=explain)['hits']
    # filter out the scores below the specified threshold
    if results['max_score'] > threshold:
        # topic title terms have to be subset of the tweet
        topic = results['hits'][0]
        title_terms = ' '.join(topic['_source']['title_terms'])
        if query.find(title_terms) > -1:
            return topic
    return None


def search_duplicate_tweets(query, threshold=3, index=INDEX):
    results = es.search(index=index, body={"query": {"match": {"tweet": query}}}, doc_type='tweets')['hits']
    if results['max_score'] > threshold:
        return results['hits'][0]
    return None


def store_tweet(topic_id, tweet_text, index=INDEX):
    es.index(index=index, doc_type='tweets', id=topic_id,
             body={'tweet': tweet_text})


def f7(seq):
    '''
    Remove duplicates from tweets preserving order
    '''
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]


class TopicListener(StreamListener):
    '''
    Overrides Tweepy class for Twitter Streaming API
    '''

    def on_status(self, status):
        author = status.user.screen_name
        # ignore retweets
        if not hasattr(status,'retweeted_status'):
            text = status.text.replace('\n', '')
            text = ' '.join([author, text])
            report = text
            if status.entities[u'user_mentions']:
                mentions = ' '.join([entity[u'name'] for entity in status.entities[u'user_mentions']])
                report += '\nMentions: ' + mentions
                text = ' '.join([text, mentions])
            if status.entities[u'urls']:
                report += '\nURL'
            if [u'media'] in status.entities.keys():
                report += '\nMEDIA'

            # preprocess tweet
            tokens = tokenize_in_es(text)
            query = ' '.join(f7(tokens))

            # query elastic search
            results = search_all(query=query, threshold=19)
            if results:
                # check duplicates
                duplicates = search_duplicate_tweets(query=query)
                if not duplicates:
                    # report tweet
                    print 'Tweet:', report
                    # sent to ES
                    print 'Query:', query
                    print results['_score']
                    title = results['_source']['title']
                    print title
                    print results['_source']['description']
                    print results['_source']['narrative']

                    topid = results['_id']

                    # send push notification
                    # resp = requests.post(API_BASE % ("tweet/%s/%s/%s" %(topid, status.id, CLIENT_IDS[0])))
                    # assert resp == '<Response [204]>'

                    twitter_client.update_status(title + ' https://twitter.com/%s/status/%s' % (author, status.id))

                    # store tweets that have been reported to ES
                    store_tweet(topid, query)
                    print '\n'

        return True


    def on_error(self, status_code):
      print status_code, 'error code'


def stream_tweets():
    '''
    Connect to Twitter API and fetch relevant tweets from the stream
    '''
    listener = TopicListener()

    # start streaming
    while True:
        try:
            stream = Stream(auth_handler, listener)
            print 'Listening...'
            stream.sample(languages=['en'])
        except Exception as e:
            # reconnect on exceptions
            print e
            continue


if __name__ == '__main__':
    stream_tweets()