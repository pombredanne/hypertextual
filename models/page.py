from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.orm.exc import NoResultFound
from .base import DeclarativeBase
from .rev import Revision
from config import SITE_URL
from diff_match_patch.diff_match_patch import diff_match_patch
from markdown import markdown
from markdown.extensions.wikilinks import WikiLinkExtension

class Page(DeclarativeBase):

    # table
    __tablename__ = 'page'

    # columns
    id = Column(Integer, primary_key=True, nullable=False)
    acct_id = Column(Integer, ForeignKey('acct.id', ondelete='CASCADE'), nullable=False)
    create_ts = Column(DateTime, default=datetime.now)

    page_name = Column(String, nullable=True)
    title = Column(String, nullable=False)
    orig_text = Column(String, nullable=False)
    curr_text = Column(String, nullable=False)
    curr_rev_num = Column(Integer, nullable=False)
    use_markdown = Column(Boolean, nullable=False)

    # relationships
    revs = relationship('Revision', order_by='Revision.id', backref='page', primaryjoin='Page.id==Revision.page_id')
    acct = None #-> Account.pages

    def __init__(self):
        self.orig_text = ''
        self.curr_text = ''
        self.curr_rev_num = None
        self.use_markdown = True

    def get_url(self, rev=None):

        # start with uid
        url = '%s/%s' % (SITE_URL, self.acct.uid)

        # add rev num if required
        if rev is not None and rev != self.curr_rev_num:
            url += '/%s' % rev

        # add page name if required
        if self.page_name is not None:
            url += '/%s' % self.page_name

        return url

    def set_title(self, session, account, title):

        # set title
        self.title = title

        # build a page name from the valid characters in the page name,
        # removing any single quotes and substituting dashes for everything else
        valid_chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
        page_name = ''
        for char in title.lower():
            if char in valid_chars:
                page_name += char
            elif char == "'":
                continue
            elif not page_name.endswith('-'):
                page_name += "-"
        page_name = page_name.strip('-')

        # limit to 30 chars
        page_name = page_name[:30].strip('-')

        # prepend underscore to numeric name
        try:
            page_name = '_%s' % int(page_name)
        except ValueError:
            pass

        # ensure uniqueness of name
        exists = lambda name: session.query(Page).\
            filter(Page.page_name==name).\
            filter(Page.acct==account).count()
        name_to_test = page_name
        i = 1
        while exists(name_to_test):
            i+=1
            name_to_test = '%s-%s' % (page_name, i)

        # set page name
        self.page_name = name_to_test

    # Generate a new revision by diffing the new text against the current text.
    def create_rev(self, new_text):

        if self.curr_rev_num is None:
            rev = Revision()
            rev.rev_num = 0
            rev.patch_text = None
            self.revs.append(rev)
            self.curr_rev_num = 0
            self.orig_text = new_text
            self.curr_text = new_text

        elif new_text != self.curr_text:
            rev = Revision()
            rev.rev_num = self.curr_rev_num + 1
            dmp = diff_match_patch()
            patches = dmp.patch_make(self.curr_text, new_text)
            rev.patch_text = dmp.patch_toText(patches)
            self.revs.append(rev)
            self.curr_rev_num = rev.rev_num
            self.curr_text = new_text

    # Get the text for a particular revision
    def get_text_for_rev(self, rev_num):
        if rev_num == 0:
            text = self.orig_text
        elif rev_num == self.curr_rev_num:
            text = self.curr_text
        else:
            # apply successive patches until the text for the
            # requested version has been reconstructed
            dmp = diff_match_patch()
            text = self.orig_text
            for rev in self.revs[1:rev_num+1]:
                patches = dmp.patch_fromText(rev.patch_text)
                text = dmp.patch_apply(patches, text)[0]
        return text

    def build_url(self, session, label, base, end):

        # todo: get wiki links to match : and | as well
        from .acct import Account
        i = label.find(':')
        if i >= 0:
            uid = label[:i]
            title = label[i+1:]
        else:
            uid = self.acct.uid
            title = label
        try:
            page = session.query(Page).\
                join(Account.pages).\
                filter(Page.title==title, Account.uid==uid).one()
            url = page.get_url()
        except NoResultFound:
            # todo: check against current user as well as page owner
            if uid==self.acct.uid:
                url = '%s/%s?action=create&title=%s' % (base, uid, title)
            else:
                url = '#'

        return url

    def get_html_for_rev(self, session, rev_num):
        text = self.get_text_for_rev(rev_num)
        build_url = lambda l,b,e: self.build_url(session, l, b, e)
        if self.use_markdown:
            linkExt = WikiLinkExtension(configs=[('build_url', build_url), ('base_url', SITE_URL)])
            html = markdown(text, extensions=[linkExt])
        else:
            html = '<pre>%s</pre>' % text
        return html