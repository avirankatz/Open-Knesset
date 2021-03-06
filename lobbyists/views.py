from django.views.generic import ListView, DetailView, TemplateView
from models import *
from django.core.exceptions import ObjectDoesNotExist
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseRedirect, Http404
import json
import sys
from links.models import Link


class LobbyistsIndexView(ListView):

    def get_queryset(self):
        return LobbyistHistory.objects.latest().lobbyists.select_related('person').order_by('person__name')

    def get_context_data(self, **kwargs):
        context = super(LobbyistsIndexView, self).get_context_data(**kwargs)
        corporations = LobbyistCorporation.objects.current_corporations().order_by('name')
        corporation_ids = corporations.values_list('id', flat=True)
        corporation_alias = LobbyistCorporationAlias.objects.filter(main_corporation__id__in=corporation_ids)
        corporation_alias = corporation_alias.values_list('main_corporation__id', 'alias_corporation__id')
        #main = dict(corporation_alias)
        alias = dict(map(reversed, corporation_alias))
        main = {}
        aliases = []
        for corporation in corporations:
            if alias.has_key(corporation.id):
                main_id = alias[corporation.id]
                if not main.has_key(main_id):
                    main[main_id] = []
                main[main_id].append(corporation.id)
                aliases.append(corporation.id)
        for corporation in corporations:
            if not main.has_key(corporation.id) and corporation.id not in aliases:
                main[corporation.id] = []
        context['alias'] = main
        corporations = LobbyistCorporation.objects.filter(id__in=main.keys()).order_by('name')
        context['corporations'] = corporations
        lobbyists_cached_data = []
        for lobbyist in context['object_list']:
            lobbyists_cached_data.append(lobbyist.cached_data)
        context['object_list'] = lobbyists_cached_data
        return context


class LobbyistCorporationsListView(TemplateView):
    template_name = 'lobbyists/lobbyistcorporation_list.html'

    def get_context_data(self):
        try:
            corporations = [c.cached_data for c in LobbyistHistory.objects.latest().main_corporations.order_by('name')]
            if not self.request.GET.get('order_by_name', ''):
                corporations = sorted(corporations, key=lambda c: c['combined_lobbyists_count'], reverse=True)
        except ObjectDoesNotExist:
            # this is meant to support case where lobbyists history data doesn't exist
            # it shouldn't happen in normal cases, only during testing or when starting from empty DB
            corporations = []
        fcs = []
        private_lobbyists_count = 0
        private_corporation = None
        for corporation in corporations:
            if not corporation['name'] and not corporation['source_id']:
                private_corporation = corporation
                private_lobbyists_count = private_lobbyists_count + corporation['combined_lobbyists_count']
            else:
            #elif corporation['combined_lobbyists_count'] > 1:
                fcs.append(corporation)
            #else:
            #    private_lobbyists_count = private_lobbyists_count + corporation['combined_lobbyists_count']
        if private_corporation is not None:
            private_corporation['is_private_lobbyists'] = True
            fcs.insert(0, private_corporation)
            private_corporation['combined_lobbyists_count'] = private_lobbyists_count
        return {
            'corporations': fcs
        }


class LobbyistDetailView(DetailView):

    model = Lobbyist

    queryset = Lobbyist.objects.all()\
        .prefetch_related('committee_meetings')\
        .prefetch_related('committee_meetings__committee')

    def get_context_data(self, **kwargs):
        context = super(LobbyistDetailView, self).get_context_data(**kwargs)
        lobbyist = context['object']
        context['represents'] = lobbyist.latest_data.represents.all()
        context['corporation'] = lobbyist.latest_corporation
        context['data'] = lobbyist.latest_data
        context['links'] = Link.objects.for_model(context['object'])
        return context


class LobbyistCorporationDetailView(DetailView):

    model = LobbyistCorporation

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.main_corporation == self.object:
            context = self.get_context_data(object=self.object)
            return self.render_to_response(context)
        else:
            return HttpResponseRedirect(self.object.main_corporation.get_absolute_url())

    def get_context_data(self, **kwargs):
        context = super(LobbyistCorporationDetailView, self).get_context_data(**kwargs)
        context['lobbyists'] = Lobbyist.objects.filter(id__in=context['object'].cached_data['combined_lobbyist_ids']).order_by('person__name')
        if context['object'] not in LobbyistCorporation.objects.current_corporations():
            context['warning_old_corporation'] = True
        context['links'] = Link.objects.for_model(context['object'])
        return context


class LobbyistRepresentDetailView(DetailView):

    model = LobbyistRepresent

    def get_context_data(self, **kwargs):
        context = super(LobbyistRepresentDetailView, self).get_context_data(**kwargs)


def LobbyistCorporationMarkAliasView(request, alias, main):
    res = {'ok': True}
    try:
        # TODO: make sure an alias corporation is not an alias for another alias corporation
        if LobbyistCorporationAlias.objects.filter(alias_corporation__id = main).count() > 0:
            raise Exception('An alias corporation cannot be used as a main corporation')
        LobbyistCorporationAlias.objects.create(main_corporation_id=main, alias_corporation_id=alias)
        LobbyistCorporation.objects.get(id=main).clear_cache()
        LobbyistCorporation.objects.get(id=alias).clear_cache()
        LobbyistHistory.objects.latest().clear_corporations_cache()
    except:
        res['ok'] = False
        res['msg'] = unicode(sys.exc_info()[1])
    return HttpResponse(json.dumps(res), content_type="application/json")


def lobbyists_auto_complete(request):
    if request.method != 'GET':
        raise Http404

    if not 'query' in request.GET:
        raise Http404

    suggestions = map(lambda lob: lob.person.name,
                      Lobbyist.objects.filter(
                          person__name__icontains=request.GET['query'])[:30])

    result = { 'query': request.GET['query'], 'suggestions':suggestions }

    return HttpResponse(json.dumps(result), mimetype='application/json')
